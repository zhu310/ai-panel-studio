import asyncio
import json
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from .database import SessionLocal, get_session
from .init_db import init_db
from .models import Discussion, DiscussionStatus, Participant, Message, DiscussionEvent, DiscussionInsight
from .schemas import CreateDiscussion, DiscussionOut, DiscussionDetail, ParticipantOut, MessageOut, InsightOut
from .discussion_service import DiscussionManager, event, generate_roster, summary_for
from .llm import ModelError

app = FastAPI(title="AI Panel Studio API", version="0.3.0")
app.state.manager = DiscussionManager()

@app.on_event("startup")
def startup():
    init_db()
    with SessionLocal.begin() as db:
        for item in db.scalars(select(Discussion).where(Discussion.status == DiscussionStatus.RUNNING)).all():
            item.status = DiscussionStatus.FAILED
            event(db, item.id, "discussion.error", {"message": "服务重启中断了讨论；历史记录已保留"})
            event(db, item.id, "discussion.status", {"status": "failed"})

def get_discussion(db: Session, discussion_id: int) -> Discussion:
    item = db.get(Discussion, discussion_id)
    if item is None:
        raise HTTPException(404, "讨论不存在")
    return item

def conflict(message: str):
    raise HTTPException(409, message)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/api/v1/discussions", response_model=DiscussionOut, status_code=201)
def create(payload: CreateDiscussion, db: Session = Depends(get_session)):
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(422, "话题不能为空")
    item = Discussion(topic=topic, expert_count=payload.expert_count)
    db.add(item); db.commit(); db.refresh(item)
    return item

@app.get("/api/v1/discussions", response_model=list[DiscussionOut])
def list_discussions(db: Session = Depends(get_session)):
    return db.scalars(select(Discussion).order_by(Discussion.created_at.desc(), Discussion.id.desc())).all()

@app.get("/api/v1/discussions/{discussion_id}", response_model=DiscussionDetail)
def detail(discussion_id: int, db: Session = Depends(get_session)):
    item = db.scalar(select(Discussion).options(selectinload(Discussion.participants))
                     .where(Discussion.id == discussion_id))
    if item is None:
        raise HTTPException(404, "讨论不存在")
    response = DiscussionDetail.model_validate(item)
    response.summary = summary_for(db, discussion_id)
    return response

@app.get("/api/v1/discussions/{discussion_id}/participants", response_model=list[ParticipantOut])
def participants(discussion_id: int, db: Session = Depends(get_session)):
    get_discussion(db, discussion_id)
    return db.scalars(select(Participant).where(Participant.discussion_id == discussion_id)
                      .order_by(Participant.id)).all()

@app.get("/api/v1/discussions/{discussion_id}/transcript", response_model=list[MessageOut])
def transcript(discussion_id: int, db: Session = Depends(get_session)):
    get_discussion(db, discussion_id)
    rows = db.scalars(select(Message).where(Message.discussion_id == discussion_id)
                      .order_by(Message.sequence)).all()
    actions = {e.payload.get("message_id"): e.payload.get("action") for e in db.scalars(
        select(DiscussionEvent).where(DiscussionEvent.discussion_id == discussion_id,
                                      DiscussionEvent.event_type == "message.created")).all()}
    return [MessageOut.model_validate(m).model_copy(update={"action": actions.get(m.id)}) for m in rows]

@app.get("/api/v1/discussions/{discussion_id}/insights", response_model=list[InsightOut])
def insights(discussion_id: int, db: Session = Depends(get_session)):
    get_discussion(db, discussion_id)
    rows = db.scalars(select(DiscussionInsight).options(selectinload(DiscussionInsight.evidence))
                      .where(DiscussionInsight.discussion_id == discussion_id)
                      .order_by(DiscussionInsight.id)).all()
    return [InsightOut(id=x.id, kind=x.kind, content=x.content, is_active=x.is_active,
                       version=x.version, evidence_message_ids=[e.message_id for e in x.evidence]) for x in rows]

@app.post("/api/v1/discussions/{discussion_id}/roster", response_model=list[ParticipantOut])
async def create_roster(discussion_id: int, request: Request):
    try:
        await generate_roster(request.app, discussion_id)
    except ValueError as exc:
        if str(exc) == "讨论不存在":
            raise HTTPException(404, str(exc)) from exc
        conflict(str(exc))
    except ModelError as exc:
        raise HTTPException(502, str(exc)) from exc
    with SessionLocal() as db:
        return db.scalars(select(Participant).where(Participant.discussion_id == discussion_id)
                          .order_by(Participant.id)).all()

@app.post("/api/v1/discussions/{discussion_id}/confirm", response_model=DiscussionOut)
async def confirm(discussion_id: int, request: Request):
    async with request.app.state.manager.lock(discussion_id):
        with SessionLocal.begin() as db:
            item = get_discussion(db, discussion_id)
            if item.status != DiscussionStatus.ROSTER_READY:
                if item.status == DiscussionStatus.CONFIRMED:
                    return DiscussionOut.model_validate(item)
                conflict("嘉宾阵容尚未就绪，无法确认")
            count = db.query(Participant).filter(Participant.discussion_id == discussion_id).count()
            if count != item.expert_count + 1:
                conflict("嘉宾数量与讨论设置不符")
            item.status = DiscussionStatus.CONFIRMED
            event(db, discussion_id, "discussion.status", {"status": "confirmed"})
            db.flush()
            return DiscussionOut.model_validate(item)

class StartBody(BaseModel):
    message_budget: int = Field(default=18, ge=4, le=24)

@app.post("/api/v1/discussions/{discussion_id}/start", status_code=202)
async def start(discussion_id: int, request: Request, body: StartBody | None = None):
    budget = (body or StartBody()).message_budget
    async with request.app.state.manager.lock(discussion_id):
        with SessionLocal.begin() as db:
            item = get_discussion(db, discussion_id)
            if item.status != DiscussionStatus.CONFIRMED:
                conflict("须先确认阵容，且讨论只能启动一次")
            item.status = DiscussionStatus.RUNNING
            event(db, discussion_id, "discussion.status", {"status": "running"})
        request.app.state.manager.start(request.app, discussion_id, budget)
    return {"status": "running", "message_budget": budget}

@app.post("/api/v1/discussions/{discussion_id}/stop")
async def stop(discussion_id: int, request: Request):
    async with request.app.state.manager.lock(discussion_id):
        with SessionLocal.begin() as db:
            item = get_discussion(db, discussion_id)
            if item.status == DiscussionStatus.STOPPED:
                return {"status": "stopped"}
            if item.status != DiscussionStatus.RUNNING:
                conflict("当前讨论未运行")
            item.status = DiscussionStatus.STOPPED
            event(db, discussion_id, "discussion.status", {"status": "stopped"})
        task = request.app.state.manager.tasks.get(discussion_id)
        if task:
            task.cancel()
    return {"status": "stopped"}

@app.get("/api/v1/discussions/{discussion_id}/events")
async def events(discussion_id: int, request: Request, after: int = 0):
    with SessionLocal() as db:
        get_discussion(db, discussion_id)
    header = request.headers.get("last-event-id")
    if header:
        try:
            after = max(after, int(header))
        except ValueError as exc:
            raise HTTPException(422, "无效的事件游标") from exc
    async def stream():
        cursor = after
        while not await request.is_disconnected():
            with SessionLocal() as db:
                rows = db.scalars(select(DiscussionEvent).where(
                    DiscussionEvent.discussion_id == discussion_id,
                    DiscussionEvent.sequence > cursor).order_by(DiscussionEvent.sequence).limit(100)).all()
                state = db.get(Discussion, discussion_id).status
                wire = [(x.sequence, x.event_type, x.payload) for x in rows]
            for sequence, kind, payload in wire:
                cursor = sequence
                data = json.dumps({"discussion_id": discussion_id, "sequence": sequence,
                                   "type": kind, "payload": payload}, ensure_ascii=False)
                yield f"id: {sequence}\nevent: {kind}\ndata: {data}\n\n"
            if state in {DiscussionStatus.COMPLETED, DiscussionStatus.STOPPED, DiscussionStatus.FAILED} and not wire:
                return
            await asyncio.sleep(0.4)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
