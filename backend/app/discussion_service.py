import asyncio
import re
from collections import Counter
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload
from .database import SessionLocal
from .models import (Discussion, DiscussionStatus, Participant, ParticipantRole, Message,
                     DiscussionEvent, DiscussionInsight, InsightEvidence, InsightKind)
from .llm import Guest, Roster, Turn, InsightBatch, ModelError, get_llm


def event(db, discussion_id: int, kind: str, payload: dict) -> DiscussionEvent:
    # Pending events in this transaction must take part in the next sequence.
    db.flush()
    number = (db.scalar(select(func.max(DiscussionEvent.sequence)).where(
        DiscussionEvent.discussion_id == discussion_id)) or 0) + 1
    record = DiscussionEvent(discussion_id=discussion_id, sequence=number,
                             event_type=kind, payload=payload)
    db.add(record)
    return record


def summary_for(db, discussion_id: int) -> str | None:
    row = db.scalar(select(DiscussionEvent).where(
        DiscussionEvent.discussion_id == discussion_id,
        DiscussionEvent.event_type == "discussion.summary").order_by(DiscussionEvent.sequence.desc()))
    return row.payload.get("text") if row else None


def roster_prompt(topic: str, count: int) -> tuple[str, str]:
    return ("你是中文圆桌讨论的嘉宾策划。只输出 JSON 对象，字段 host 与 experts；每人有 name、title、background、stance、color。"
            "颜色必须为不同的 #RRGGBB。专家的专业与立场应互补且有真实分歧；主持人保持中立。",
            f"议题：{topic}\n严格生成一名主持人和 {count} 名专家。")


async def generate_roster(app, discussion_id: int):
    async with app.state.manager.lock(discussion_id):
        with SessionLocal() as db:
            discussion = db.get(Discussion, discussion_id)
            if discussion is None:
                raise ValueError("讨论不存在")
            if discussion.status == DiscussionStatus.ROSTER_READY:
                return
            if discussion.status != DiscussionStatus.DRAFT:
                raise ValueError("当前状态不能生成嘉宾")
            topic, count = discussion.topic, discussion.expert_count
        system, user = roster_prompt(topic, count)
        roster: Roster = await get_llm(app).json(system, user, Roster)
        if len(roster.experts) != count:
            raise ModelError(f"模型返回 {len(roster.experts)} 名专家，预期 {count} 名")
        guests = [roster.host, *roster.experts]
        if len({g.name for g in guests}) != len(guests) or len({g.color.lower() for g in guests}) != len(guests):
            raise ModelError("嘉宾姓名或颜色重复")
        if len({g.stance.strip() for g in roster.experts}) < 2:
            raise ModelError("专家立场缺乏差异")
        with SessionLocal.begin() as db:
            discussion = db.get(Discussion, discussion_id)
            if discussion.status != DiscussionStatus.DRAFT:
                raise ValueError("讨论状态已变化")
            for index, guest in enumerate(guests):
                db.add(Participant(discussion_id=discussion_id,
                    role=ParticipantRole.HOST if index == 0 else ParticipantRole.EXPERT,
                    **guest.model_dump()))
            discussion.status = DiscussionStatus.ROSTER_READY
            event(db, discussion_id, "discussion.status", {"status": "roster_ready"})


def transcript_context(topic: str, people: list[Participant], messages: list[Message], budget: int) -> str:
    profiles = "\n".join(f"{p.id} {p.name}（{p.title}）：{p.stance}" for p in people)
    recent = "\n".join(f"#{m.sequence} {next(p.name for p in people if p.id == m.speaker_id)}：{m.content}"
                       for m in messages[-8:])
    counts = Counter(m.speaker_id for m in messages)
    uncovered = [p.name for p in people if p.role == ParticipantRole.EXPERT and counts[p.id] == 0]
    last_speaker = messages[-1].speaker_id if messages else "无"
    return (f"议题：{topic}\n嘉宾：\n{profiles}\n已公开发言：{len(messages)}/{budget}\n"
            f"上一位发言者 ID：{last_speaker}；下一位 speaker_id 不得与其相同。\n"
            f"发言次数：{dict(counts)}\n尚未参与的专家：{uncovered or '无'}\n最近发言：\n{recent or '尚无'}")


def validate_turn(turn: Turn, people: list[Participant], messages: list[Message], budget: int):
    ids = {p.id for p in people}
    host = next(p for p in people if p.role == ParticipantRole.HOST)
    if turn.speaker_id not in ids:
        raise ModelError("模型选择了不存在的发言人")
    if not messages and (turn.speaker_id != host.id or turn.action != "open"):
        raise ModelError("首条发言必须由主持人开场")
    if turn.action in {"open", "invite", "moderate"} and turn.speaker_id != host.id:
        raise ModelError("主持动作不能由专家执行")
    if turn.action in {"answer", "add", "rebut", "question", "interrupt"} and turn.speaker_id == host.id:
        raise ModelError("专家动作不能由主持人执行")
    if turn.hand_raised and turn.speaker_id == host.id:
        raise ModelError("主持人不能申请发言")
    if turn.action == "interrupt" and not turn.hand_raised:
        raise ModelError("插话必须同时标记申请发言")
    if messages and turn.speaker_id == messages[-1].speaker_id:
        raise ModelError("同一人不能连续独白")
    if len(re.findall(r"[。！？!?]", turn.text)) > 2 or len(turn.text) > 160:
        raise ModelError("公开发言超过一至两句或 160 字")
    if any(turn.text.strip() == m.content.strip() for m in messages):
        raise ModelError("公开发言重复")
    experts = {p.id for p in people if p.role == ParticipantRole.EXPERT}
    spoken_after = {m.speaker_id for m in messages} | {turn.speaker_id}
    uncovered_after = experts - spoken_after
    turn_limit = min(budget - 1, 23)
    remaining_after = turn_limit - (len(messages) + 1)
    if len(uncovered_after) > remaining_after:
        raise ModelError("剩余发言位不足，必须优先选择尚未参与的专家")
    minimum_turns = max(4, len(experts) + 2)
    if turn.finish and (len(messages) + 1 < minimum_turns or uncovered_after):
        raise ModelError("讨论过早结束；所有专家至少发言一次且完成必要交锋后才能结束")


def compact_public_text(value: str) -> str:
    """Keep the model's own words while enforcing the public utterance budget."""
    text = " ".join(value.split())
    sentences = re.findall(r"[^。！？!?]+[。！？!?]?", text)
    text = "".join(sentences[:2]).strip()
    if len(text) > 160:
        boundary = max(text.rfind(mark, 0, 159) for mark in "，；;、")
        text = (text[:boundary] if boundary >= 35 else text[:159]).rstrip("，；;、 ") + "。"
    if text and text[-1] not in "。！？!?":
        text = text[:159] + "。"
    return text


def turn_prompt(topic: str, people: list[Participant], messages: list[Message], budget: int):
    system = ("你主持真实的中文专家圆桌讨论。只输出 JSON：speaker_id 整数、action、text、focus、hand_raised、finish。"
              "action 只能是 open/invite/answer/add/rebut/question/interrupt/moderate。首条主持人 open。"
              "只要已有发言，speaker_id 绝不能与上一位发言者相同；主持人开场后的下一位必须是专家并使用专家动作。"
              "后续从专家主动回应、反驳、追问和主持串联中按上下文动态选择；不可固定轮询。"
              "引用或回应此前具体观点；每次 text 一至两句，最好少于 90 字，硬上限 160 字。focus 是公开关注点，不是思维链。"
              "主持人应在开场后按讨论进展适时用 invite 或 moderate 追问和串联，而不是固定轮询。"
              "专家申请发言时设置 hand_raised=true；interrupt 必须同时申请发言。"
              "finish 仅在所有专家至少发言一次、已有回应或交锋且观点充分后为 true。")
    return system, transcript_context(topic, people, messages, budget)


def insight_prompt(topic: str, people: list[Participant], messages: list[Message]):
    names = {p.id: p.name for p in people}
    lines = "\n".join(f"#{m.sequence} {names[m.speaker_id]}：{m.content}" for m in messages)
    return ("仅根据给定公开发言提取已有共识或分歧，返回 JSON 对象 items。每项含 kind"
            "（consensus/disagreement）、content、evidence_sequences（真实发言序号数组）。"
            "证据不足时返回空数组；合并同义结论，每类最多两项。", f"议题：{topic}\n{lines}")


def save_insights(db, discussion_id: int, candidates: InsightBatch, messages: list[Message]):
    by_seq = {m.sequence: m for m in messages}
    changed = []
    for candidate in candidates.items:
        evidence = [by_seq.get(n) for n in candidate.evidence_sequences]
        if not evidence or any(m is None or m.discussion_id != discussion_id for m in evidence):
            continue
        kind = InsightKind(candidate.kind)
        same = db.scalar(select(DiscussionInsight).where(
            DiscussionInsight.discussion_id == discussion_id,
            DiscussionInsight.kind == kind,
            DiscussionInsight.content == candidate.content))
        if same:
            insight = same
            insight.version += 1
        else:
            existing = db.scalars(select(DiscussionInsight).where(
                DiscussionInsight.discussion_id == discussion_id,
                DiscussionInsight.kind == kind,
                DiscussionInsight.is_active.is_(True)).order_by(DiscussionInsight.id)).all()
            if len(existing) >= 2:
                insight = existing[0]
                insight.content = candidate.content
                insight.version += 1
                for old_evidence in list(insight.evidence):
                    db.delete(old_evidence)
                db.flush()
                db.expire(insight, ["evidence"])
            else:
                insight = DiscussionInsight(discussion_id=discussion_id, kind=kind, content=candidate.content)
                db.add(insight)
                db.flush()
        known = {e.message_id for e in insight.evidence}
        for message in evidence:
            if message.id not in known:
                db.add(InsightEvidence(insight_id=insight.id, message_id=message.id))
        changed.append(insight.id)
    if changed:
        event(db, discussion_id, "insights.updated", {"insight_ids": changed})


class DiscussionManager:
    def __init__(self):
        self.tasks: dict[int, asyncio.Task] = {}
        self.locks: dict[int, asyncio.Lock] = {}

    def lock(self, discussion_id: int) -> asyncio.Lock:
        return self.locks.setdefault(discussion_id, asyncio.Lock())

    def start(self, app, discussion_id: int, budget: int):
        previous = self.tasks.get(discussion_id)
        if previous and not previous.done():
            raise ValueError("讨论已经运行")
        task = asyncio.create_task(run_discussion(app, discussion_id, budget))
        self.tasks[discussion_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(discussion_id, None)
                               if self.tasks.get(discussion_id) is task else None)


async def run_discussion(app, discussion_id: int, budget: int):
    try:
        turn_limit = min(budget - 1, 23)  # Reserve the final public message for the host's summary.
        for _ in range(turn_limit):
            with SessionLocal() as db:
                discussion = db.get(Discussion, discussion_id)
                if discussion is None or discussion.status != DiscussionStatus.RUNNING:
                    return
                people = db.scalars(select(Participant).where(Participant.discussion_id == discussion_id)).all()
                messages = db.scalars(select(Message).where(Message.discussion_id == discussion_id)
                                      .order_by(Message.sequence)).all()
                topic = discussion.topic
            system, user = turn_prompt(topic, people, messages, budget)
            for attempt in range(2):
                turn: Turn = await get_llm(app).json(system, user, Turn)
                turn.text = compact_public_text(turn.text)
                try:
                    validate_turn(turn, people, messages, budget)
                    break
                except ModelError as exc:
                    if attempt:
                        raise
                    user += f"\n上次候选无效：{exc}。请修正，并仅返回一至两句、160 字以内的公开发言。"
            async with app.state.manager.lock(discussion_id):
                with SessionLocal.begin() as db:
                    discussion = db.get(Discussion, discussion_id)
                    if discussion.status != DiscussionStatus.RUNNING:
                        return
                    if turn.hand_raised:
                        event(db, discussion_id, "participant.hand_raised", {
                            "participant_id": turn.speaker_id, "focus": turn.focus, "action": turn.action})
            # Hand raising is a distinct observable state, not overwritten in the same transaction.
            if turn.hand_raised:
                await asyncio.sleep(0.6)
            async with app.state.manager.lock(discussion_id):
                with SessionLocal.begin() as db:
                    discussion = db.get(Discussion, discussion_id)
                    if discussion.status != DiscussionStatus.RUNNING:
                        return
                    event(db, discussion_id, "participant.status", {"participant_id": turn.speaker_id,
                                                                      "status": "preparing", "focus": turn.focus,
                                                                      "action": turn.action})
            # Give subscribers time to observe the persisted preparation event.
            await asyncio.sleep(0.45)
            async with app.state.manager.lock(discussion_id):
                with SessionLocal.begin() as db:
                    discussion = db.get(Discussion, discussion_id)
                    if discussion.status != DiscussionStatus.RUNNING:
                        return
                    event(db, discussion_id, "participant.status", {"participant_id": turn.speaker_id,
                                                                      "status": "speaking", "focus": turn.focus,
                                                                      "action": turn.action})
                    number = len(messages) + 1
                    message = Message(discussion_id=discussion_id, speaker_id=turn.speaker_id,
                                      sequence=number, content=turn.text)
                    db.add(message)
                    db.flush()
                    event(db, discussion_id, "message.created", {"message_id": message.id,
                                                                     "speaker_id": turn.speaker_id,
                                                                     "sequence": number, "content": turn.text,
                                                                     "action": turn.action})
            await asyncio.sleep(0.75)
            async with app.state.manager.lock(discussion_id):
                with SessionLocal.begin() as db:
                    if db.get(Discussion, discussion_id).status != DiscussionStatus.RUNNING:
                        return
                    event(db, discussion_id, "participant.status", {"participant_id": turn.speaker_id,
                                                                      "status": "idle", "focus": turn.focus})
            if number >= 4 and (number % 3 == 0 or turn.finish or number == turn_limit):
                try:
                    with SessionLocal() as db:
                        all_messages = db.scalars(select(Message).where(Message.discussion_id == discussion_id)
                                                  .order_by(Message.sequence)).all()
                    s, u = insight_prompt(topic, people, all_messages)
                    batch: InsightBatch = await get_llm(app).json(s, u, InsightBatch)
                    async with app.state.manager.lock(discussion_id):
                        with SessionLocal.begin() as db:
                            if db.get(Discussion, discussion_id).status != DiscussionStatus.RUNNING:
                                return
                            current = db.scalars(select(Message).where(Message.discussion_id == discussion_id)).all()
                            save_insights(db, discussion_id, batch, current)
                except ModelError:
                    pass  # An insight extraction failure does not erase a valid discussion.
            if turn.finish:
                break
        with SessionLocal() as db:
            discussion = db.get(Discussion, discussion_id)
            if discussion.status != DiscussionStatus.RUNNING:
                return
            messages = db.scalars(select(Message).where(Message.discussion_id == discussion_id)
                                  .order_by(Message.sequence)).all()
            people = db.scalars(select(Participant).where(Participant.discussion_id == discussion_id)).all()
        recap = await get_llm(app).json(
            "你是圆桌主持人。仅返回 JSON 对象，字段 text 为自然中文总结，概括已发表观点、共识与分歧；不可编造。",
            transcript_context(topic, people, messages, budget), Summary)
        async with app.state.manager.lock(discussion_id):
            with SessionLocal.begin() as db:
                discussion = db.get(Discussion, discussion_id)
                if discussion.status != DiscussionStatus.RUNNING:
                    return
                host = next(p for p in people if p.role == ParticipantRole.HOST)
                message = Message(discussion_id=discussion_id, speaker_id=host.id,
                                  sequence=len(messages) + 1, content=recap.text)
                db.add(message)
                db.flush()
                event(db, discussion_id, "message.created", {"message_id": message.id,
                                                                 "speaker_id": host.id,
                                                                 "sequence": message.sequence,
                                                                 "content": recap.text, "action": "summary"})
                event(db, discussion_id, "discussion.summary", {"text": recap.text})
                discussion.status = DiscussionStatus.COMPLETED
                event(db, discussion_id, "discussion.status", {"status": "completed"})
    except asyncio.CancelledError:
        return
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ModelError) else f"讨论执行失败：{type(exc).__name__}"
        async with app.state.manager.lock(discussion_id):
            with SessionLocal.begin() as db:
                discussion = db.get(Discussion, discussion_id)
                if discussion and discussion.status == DiscussionStatus.RUNNING:
                    discussion.status = DiscussionStatus.FAILED
                    event(db, discussion_id, "discussion.error", {"message": reason})
                    event(db, discussion_id, "discussion.status", {"status": "failed"})


from pydantic import BaseModel, Field
class Summary(BaseModel):
    text: str = Field(min_length=10, max_length=1200)
