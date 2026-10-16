from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from .database import get_session
from .models import Discussion, Participant, Message, DiscussionInsight
from .schemas import CreateDiscussion, DiscussionOut, DiscussionDetail, ParticipantOut, MessageOut, InsightOut

app=FastAPI(title="AI Panel Studio API", version="0.1.0")
def get_discussion(db:Session, discussion_id:int)->Discussion:
    item=db.scalar(select(Discussion).where(Discussion.id==discussion_id))
    if not item: raise HTTPException(404,"讨论不存在")
    return item
@app.get("/health")
def health(): return {"status":"ok"}
@app.post("/api/v1/discussions",response_model=DiscussionOut,status_code=status.HTTP_201_CREATED)
def create(payload:CreateDiscussion,db:Session=Depends(get_session)):
    topic=payload.topic.strip()
    if not topic: raise HTTPException(422,"话题不能为空")
    item=Discussion(topic=topic,expert_count=payload.expert_count); db.add(item); db.commit(); db.refresh(item); return item
@app.get("/api/v1/discussions",response_model=list[DiscussionOut])
def list_discussions(db:Session=Depends(get_session)):
    return db.scalars(select(Discussion).order_by(Discussion.created_at.desc(),Discussion.id.desc())).all()
@app.get("/api/v1/discussions/{discussion_id}",response_model=DiscussionDetail)
def detail(discussion_id:int,db:Session=Depends(get_session)):
    return db.scalar(select(Discussion).options(selectinload(Discussion.participants)).where(Discussion.id==discussion_id)) or (_ for _ in ()).throw(HTTPException(404,"讨论不存在"))
@app.get("/api/v1/discussions/{discussion_id}/participants",response_model=list[ParticipantOut])
def participants(discussion_id:int,db:Session=Depends(get_session)):
    get_discussion(db,discussion_id); return db.scalars(select(Participant).where(Participant.discussion_id==discussion_id).order_by(Participant.id)).all()
@app.get("/api/v1/discussions/{discussion_id}/transcript",response_model=list[MessageOut])
def transcript(discussion_id:int,db:Session=Depends(get_session)):
    get_discussion(db,discussion_id); return db.scalars(select(Message).where(Message.discussion_id==discussion_id).order_by(Message.sequence)).all()
@app.get("/api/v1/discussions/{discussion_id}/insights",response_model=list[InsightOut])
def insights(discussion_id:int,db:Session=Depends(get_session)):
    get_discussion(db,discussion_id); rows=db.scalars(select(DiscussionInsight).where(DiscussionInsight.discussion_id==discussion_id).order_by(DiscussionInsight.id)).all()
    return [InsightOut(id=x.id,kind=x.kind,content=x.content,is_active=x.is_active,version=x.version,evidence_message_ids=[e.message_id for e in x.evidence]) for x in rows]
