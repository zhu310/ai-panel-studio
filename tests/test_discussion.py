import asyncio
import re
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.app.api import app
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import (Discussion, DiscussionStatus, Participant, ParticipantRole,
                                Message, DiscussionEvent, DiscussionInsight, InsightKind)
from backend.app.llm import Guest, Roster, Turn, InsightBatch, InsightCandidate, ModelError
from backend.app.discussion_service import (run_discussion, Summary, compact_public_text,
                                            validate_turn, turn_prompt, insight_prompt)
from backend.app.discussion_service import save_insights

class FakeLLM:
    def __init__(self):
        self.turns = {}
        self.fail = False
    async def json(self, system, user, schema):
        if self.fail:
            raise ModelError("受控模型故障")
        if schema is Roster:
            return Roster(host=Guest(name="主持", title="主持人", background="跨领域", stance="中立追问", color="#112233"),
                          experts=[Guest(name=f"专家{i}", title=f"领域{i}研究员", background=f"领域{i}",
                                         stance=f"立场{i}：关注不同条件", color=f"#2233{i:02x}") for i in range(4)])
        if schema is Turn:
            topic = user.splitlines()[0]
            self.turns[topic] = self.turns.get(topic, 0) + 1
            turn_number = self.turns[topic]
            ids = [int(x) for x in re.findall(r"^(\d+) .+（", user, re.MULTILINE)]
            # All experts participate; the host re-enters and expert 2 speaks twice.
            sequence = [(ids[0], "open", False), (ids[2], "answer", False),
                        (ids[1], "rebut", True), (ids[0], "moderate", False),
                        (ids[3], "add", False), (ids[4], "interrupt", True)]
            speaker, action, raised = sequence[min(turn_number - 1, 5)]
            return Turn(speaker_id=speaker, action=action,
                        text=f"第{turn_number}轮：针对上一观点提出具体条件。", focus="讨论实施条件",
                        hand_raised=raised, finish=turn_number == 6)
        if schema is InsightBatch:
            return InsightBatch(items=[InsightCandidate(kind="disagreement", content="实施条件仍存在实质差异", evidence_sequences=[2, 3])])
        if schema is Summary:
            return Summary(text="主持人总结：专家同意继续论证，但在实施条件上仍有分歧，后续应核验现实证据。")
        raise AssertionError(schema)

def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app.state.manager.tasks.clear()
    app.state.manager.locks.clear()
    app.state.llm = FakeLLM()

def test_public_text_compaction_preserves_sentence_boundaries():
    long_text = "这个方案有收益，" + "但必须有可验证的课程目标，" * 12 + "才能推广。另一个争议仍需讨论。第三句不能出现。"
    result = compact_public_text(long_text)
    assert len(result) <= 160 and result.endswith("。") and "第三句" not in result

def test_turn_prompt_explicitly_blocks_reselecting_last_speaker():
    host = Participant(id=10, discussion_id=1, role=ParticipantRole.HOST, name="主持",
                       title="主持人", background="教育", stance="中立", color="#112233")
    expert = Participant(id=11, discussion_id=1, role=ParticipantRole.EXPERT, name="专家",
                         title="教授", background="教育", stance="审慎", color="#223344")
    opening = Message(id=1, discussion_id=1, speaker_id=10, sequence=1, content="欢迎讨论。")
    system, user = turn_prompt("高校 AI 助教", [host, expert], [opening], 18)
    assert "speaker_id 绝不能与上一位发言者相同" in system
    assert "主持人开场后的下一位必须是专家" in system
    assert "上一位发言者 ID：10" in user

def test_roster_confirm_and_duplicate_generation():
    with TestClient(app) as client:
        d = client.post("/api/v1/discussions", json={"topic":"议题"}).json()
        did = d["id"]
        assert client.post(f"/api/v1/discussions/{did}/confirm").status_code == 409
        assert client.post(f"/api/v1/discussions/{did}/roster").status_code == 200
        assert len(client.post(f"/api/v1/discussions/{did}/roster").json()) == 5
        assert client.post(f"/api/v1/discussions/{did}/confirm").json()["status"] == "confirmed"
        assert client.post(f"/api/v1/discussions/{did}/roster").status_code == 409

def test_full_run_insight_evidence_and_event_order():
    with TestClient(app) as client:
        did = client.post("/api/v1/discussions", json={"topic":"议题"}).json()["id"]
        client.post(f"/api/v1/discussions/{did}/roster")
        client.post(f"/api/v1/discussions/{did}/confirm")
        with SessionLocal.begin() as db:
            db.get(Discussion, did).status = DiscussionStatus.RUNNING
        asyncio.run(run_discussion(app, did, 7))
        detail = client.get(f"/api/v1/discussions/{did}").json()
        with SessionLocal() as db:
            failure = db.scalar(select(DiscussionEvent).where(DiscussionEvent.discussion_id == did,
                DiscussionEvent.event_type == "discussion.error"))
        assert detail["status"] == "completed" and detail["summary"], failure.payload if failure else None
        messages = client.get(f"/api/v1/discussions/{did}/transcript").json()
        assert len(messages) == 7
        assert [m["speaker_id"] for m in messages[:6]] == [1, 3, 2, 1, 4, 5]
        insight = client.get(f"/api/v1/discussions/{did}/insights").json()[0]
        assert insight["kind"] == "disagreement"
        assert len(insight["evidence_message_ids"]) == 2
        with SessionLocal() as db:
            events = db.scalars(select(DiscussionEvent).where(DiscussionEvent.discussion_id == did)
                                .order_by(DiscussionEvent.sequence)).all()
            assert [e.sequence for e in events] == list(range(1, len(events) + 1))
            assert any(e.event_type == "participant.hand_raised" for e in events)

def test_model_error_is_visible_and_persisted():
    with TestClient(app) as client:
        did = client.post("/api/v1/discussions", json={"topic":"议题"}).json()["id"]
        app.state.llm.fail = True
        assert client.post(f"/api/v1/discussions/{did}/roster").status_code == 502
        assert client.get(f"/api/v1/discussions/{did}").json()["status"] == "draft"

def test_wrong_expert_count_does_not_persist_roster():
    class WrongCount(FakeLLM):
        async def json(self, system, user, schema):
            result = await super().json(system, user, schema)
            if schema is Roster:
                result.experts.pop()
            return result
    app.state.llm = WrongCount()
    with TestClient(app) as client:
        did = client.post("/api/v1/discussions", json={"topic":"数量校验"}).json()["id"]
        assert client.post(f"/api/v1/discussions/{did}/roster").status_code == 502
        assert client.get(f"/api/v1/discussions/{did}/participants").json() == []

def test_two_discussions_are_isolated():
    with TestClient(app) as client:
        ids = []
        for topic in ("甲", "乙"):
            did = client.post("/api/v1/discussions", json={"topic": topic}).json()["id"]
            client.post(f"/api/v1/discussions/{did}/roster")
            client.post(f"/api/v1/discussions/{did}/confirm")
            ids.append(did)
        assert ids[0] != ids[1]
        assert set(p["id"] for p in client.get(f"/api/v1/discussions/{ids[0]}/participants").json()).isdisjoint(
            p["id"] for p in client.get(f"/api/v1/discussions/{ids[1]}/participants").json())
        assert client.get(f"/api/v1/discussions/{ids[1]}/transcript").json() == []

def test_start_sse_replay_and_duplicate_start():
    with TestClient(app) as client:
        did = client.post("/api/v1/discussions", json={"topic":"回放测试"}).json()["id"]
        assert client.post(f"/api/v1/discussions/{did}/roster").status_code == 200
        assert client.post(f"/api/v1/discussions/{did}/confirm").status_code == 200
        assert client.post(f"/api/v1/discussions/{did}/start", json={"message_budget":7}).status_code == 202
        assert client.post(f"/api/v1/discussions/{did}/start").status_code == 409
        for _ in range(250):
            if client.get(f"/api/v1/discussions/{did}").json()["status"] == "completed": break
            time.sleep(.05)
        assert client.get(f"/api/v1/discussions/{did}").json()["status"] == "completed"
        wire = client.get(f"/api/v1/discussions/{did}/events").text
        assert "event: message.created" in wire and "event: insights.updated" in wire
        replay = client.get(f"/api/v1/discussions/{did}/events?after=2").text
        assert "id: 1\n" not in replay and "id: 2\n" not in replay
        header_replay = client.get(f"/api/v1/discussions/{did}/events", headers={"Last-Event-ID": "2"}).text
        assert "id: 1\n" not in header_replay and "id: 2\n" not in header_replay

def test_startup_marks_orphan_running_failed_and_preserves_history():
    with SessionLocal.begin() as db:
        item = Discussion(topic="进程重启恢复", expert_count=2, status=DiscussionStatus.RUNNING)
        db.add(item); db.flush(); did = item.id
    with TestClient(app) as client:
        detail = client.get(f"/api/v1/discussions/{did}").json()
        assert detail["status"] == "failed"
        wire = client.get(f"/api/v1/discussions/{did}/events").text
        assert "event: discussion.error" in wire
        assert "event: discussion.status" in wire

def test_stop_cancels_future_messages():
    class SlowFake(FakeLLM):
        async def json(self, system, user, schema):
            if schema is Turn:
                await asyncio.sleep(.5)
            return await super().json(system, user, schema)
    app.state.llm = SlowFake()
    with TestClient(app) as client:
        did = client.post("/api/v1/discussions", json={"topic":"停止测试"}).json()["id"]
        client.post(f"/api/v1/discussions/{did}/roster")
        client.post(f"/api/v1/discussions/{did}/confirm")
        assert client.post(f"/api/v1/discussions/{did}/start", json={"message_budget":7}).status_code == 202
        assert client.post(f"/api/v1/discussions/{did}/stop").json()["status"] == "stopped"
        time.sleep(.7)
        assert client.get(f"/api/v1/discussions/{did}/transcript").json() == []
        assert client.post(f"/api/v1/discussions/{did}/stop").status_code == 200

def test_insight_rejects_cross_discussion_evidence():
    with SessionLocal.begin() as db:
        a = Discussion(topic="甲", expert_count=2)
        b = Discussion(topic="乙", expert_count=2)
        db.add_all([a, b]); db.flush()
        foreign = Message(discussion_id=b.id, speaker_id=1, sequence=1, content="乙的观点")
        # The foreign key is deliberately fulfilled by adding a participant in B.
        from backend.app.models import Participant, ParticipantRole
        guest = Participant(discussion_id=b.id, role=ParticipantRole.HOST, name="乙主持",
                            title="主持", background="研究", stance="中立", color="#123456")
        db.add(guest); db.flush(); foreign.speaker_id = guest.id
        db.add(foreign); db.flush()
        save_insights(db, a.id, InsightBatch(items=[InsightCandidate(
            kind="consensus", content="错误地引用另一场讨论", evidence_sequences=[1])]), [foreign])
        aid = a.id
    with SessionLocal() as db:
        assert db.scalars(select(DiscussionInsight).where(DiscussionInsight.discussion_id == aid)).all() == []

def test_insight_limit_does_not_overwrite_unrelated_records():
    from backend.app.models import Participant, ParticipantRole
    with SessionLocal.begin() as db:
        d = Discussion(topic="更新测试", expert_count=2)
        db.add(d); db.flush()
        p = Participant(discussion_id=d.id, role=ParticipantRole.HOST, name="主持", title="主持",
                        background="研究", stance="中立", color="#123456")
        db.add(p); db.flush()
        messages = [Message(discussion_id=d.id, speaker_id=p.id, sequence=n, content=f"发言{n}") for n in (1, 2)]
        db.add_all(messages); db.flush()
        for text in ("第一项已有共识", "第二项已有共识", "更新后的新共识"):
            save_insights(db, d.id, InsightBatch(items=[InsightCandidate(
                kind="consensus", content=text, evidence_sequences=[1, 2])]), messages)
        did = d.id
    with SessionLocal() as db:
        rows = db.scalars(select(DiscussionInsight).where(DiscussionInsight.discussion_id == did)).all()
        assert len(rows) == 2
        assert {row.content for row in rows} == {"第一项已有共识", "第二项已有共识"}
        assert all(len(row.evidence) == 2 for row in rows)

def test_exact_duplicate_insight_is_idempotent():
    from backend.app.models import Participant, ParticipantRole
    with SessionLocal.begin() as db:
        d = Discussion(topic="重复测试", expert_count=2); db.add(d); db.flush()
        p = Participant(discussion_id=d.id, role=ParticipantRole.EXPERT, name="专家", title="研究员",
                        background="研究", stance="审慎", color="#123456"); db.add(p); db.flush()
        messages = [Message(discussion_id=d.id, speaker_id=p.id, sequence=1, content="公开证据")]
        db.add_all(messages); db.flush()
        candidate = InsightCandidate(kind="consensus", content="应先小范围试点再评估", evidence_sequences=[1])
        save_insights(db, d.id, InsightBatch(items=[candidate]), messages)
        save_insights(db, d.id, InsightBatch(items=[candidate]), messages)
        did = d.id
    with SessionLocal() as db:
        rows = db.scalars(select(DiscussionInsight).where(DiscussionInsight.discussion_id == did)).all()
        events = db.scalars(select(DiscussionEvent).where(
            DiscussionEvent.discussion_id == did, DiscussionEvent.event_type == "insights.updated")).all()
        assert len(rows) == 1 and rows[0].version == 1
        assert len(events) == 1

def test_semantic_paraphrase_does_not_create_duplicate_across_batches():
    from backend.app.models import Participant, ParticipantRole
    with SessionLocal.begin() as db:
        d = Discussion(topic="岗位变化", expert_count=2)
        db.add(d); db.flush()
        p = Participant(discussion_id=d.id, role=ParticipantRole.EXPERT, name="专家", title="研究员",
                        background="劳动力市场", stance="关注岗位入口", color="#123456")
        db.add(p); db.flush()
        messages = [Message(discussion_id=d.id, speaker_id=p.id, sequence=n, content=f"发言{n}") for n in (1, 2)]
        db.add_all(messages); db.flush()
        save_insights(db, d.id, InsightBatch(items=[InsightCandidate(
            kind="disagreement", content="转向人工复核后能否保住初级岗位入口仍有分歧",
            evidence_sequences=[1, 2], concept_key="初级岗位入口可持续性")]), messages)
        original = db.scalar(select(DiscussionInsight).where(DiscussionInsight.discussion_id == d.id))
        original_id = original.id
        save_insights(db, d.id, InsightBatch(items=[InsightCandidate(
            kind="disagreement", content="初级工程师改做验证工作是否仍能维持原有就业入口尚无共识",
            evidence_sequences=[1, 2], existing_insight_id=original_id,
            concept_key="初级岗位入口可持续性")]), messages)
        did = d.id
    with SessionLocal() as db:
        rows = db.scalars(select(DiscussionInsight).where(DiscussionInsight.discussion_id == did)).all()
        assert len(rows) == 1

def test_semantic_paraphrases_in_one_batch_do_not_create_duplicates():
    from backend.app.models import Participant, ParticipantRole
    with SessionLocal.begin() as db:
        d = Discussion(topic="岗位变化", expert_count=2)
        db.add(d); db.flush()
        p = Participant(discussion_id=d.id, role=ParticipantRole.EXPERT, name="专家", title="研究员",
                        background="劳动力市场", stance="关注岗位入口", color="#123456")
        db.add(p); db.flush()
        messages = [Message(discussion_id=d.id, speaker_id=p.id, sequence=n, content=f"发言{n}") for n in (1, 2)]
        db.add_all(messages); db.flush()
        save_insights(db, d.id, InsightBatch(items=[
            InsightCandidate(kind="disagreement", content="转向人工复核后能否保住初级岗位入口仍有分歧",
                             evidence_sequences=[1, 2], concept_key="初级岗位入口可持续性"),
            InsightCandidate(kind="disagreement", content="初级工程师改做验证工作是否仍能维持原有就业入口尚无共识",
                             evidence_sequences=[1, 2], concept_key="初级岗位入口可持续性"),
        ]), messages)
        did = d.id
    with SessionLocal() as db:
        rows = db.scalars(select(DiscussionInsight).where(DiscussionInsight.discussion_id == did)).all()
        assert len(rows) == 1

def test_insight_update_keeps_identity_and_unions_new_evidence():
    from backend.app.models import Participant, ParticipantRole
    with SessionLocal.begin() as db:
        d = Discussion(topic="证据更新", expert_count=2); db.add(d); db.flush()
        p = Participant(discussion_id=d.id, role=ParticipantRole.EXPERT, name="专家", title="研究员",
                        background="研究", stance="审慎", color="#123456"); db.add(p); db.flush()
        messages = [Message(discussion_id=d.id, speaker_id=p.id, sequence=n, content=f"证据{n}") for n in (1, 2)]
        db.add_all(messages); db.flush()
        save_insights(db, d.id, InsightBatch(items=[InsightCandidate(
            kind="consensus", content="先试点再决定推广", evidence_sequences=[1], concept_key="推广节奏")]), messages)
        original = db.scalar(select(DiscussionInsight).where(DiscussionInsight.discussion_id == d.id))
        original_id = original.id
        save_insights(db, d.id, InsightBatch(items=[InsightCandidate(
            kind="consensus", content="应在试点评估后再扩大使用范围", evidence_sequences=[2],
            existing_insight_id=original_id, concept_key="推广节奏")]), messages)
        message_ids = {message.id for message in messages}
        did = d.id
    with SessionLocal() as db:
        row = db.scalar(select(DiscussionInsight).options(selectinload(DiscussionInsight.evidence)).where(
            DiscussionInsight.discussion_id == did))
        assert row.id == original_id and row.version == 2
        assert {link.message_id for link in row.evidence} == message_ids

def test_same_evidence_can_support_two_distinct_insights():
    from backend.app.models import Participant, ParticipantRole
    with SessionLocal.begin() as db:
        d = Discussion(topic="多维影响", expert_count=2); db.add(d); db.flush()
        p = Participant(discussion_id=d.id, role=ParticipantRole.EXPERT, name="专家", title="研究员",
                        background="研究", stance="审慎", color="#123456"); db.add(p); db.flush()
        messages = [Message(discussion_id=d.id, speaker_id=p.id, sequence=n, content=f"综合发言{n}") for n in (1, 2)]
        db.add_all(messages); db.flush()
        save_insights(db, d.id, InsightBatch(items=[
            InsightCandidate(kind="disagreement", content="初级岗位数量是否下降仍有分歧",
                             evidence_sequences=[1, 2], concept_key="岗位数量"),
            InsightCandidate(kind="disagreement", content="高校培养内容应如何调整仍有分歧",
                             evidence_sequences=[1, 2], concept_key="培养方案"),
        ]), messages)
        did = d.id
    with SessionLocal() as db:
        rows = db.scalars(select(DiscussionInsight).where(DiscussionInsight.discussion_id == did)).all()
        assert len(rows) == 2
        assert {row.content for row in rows} == {"初级岗位数量是否下降仍有分歧", "高校培养内容应如何调整仍有分歧"}

def test_existing_insight_id_cannot_cross_discussions():
    from backend.app.models import Participant, ParticipantRole
    with SessionLocal.begin() as db:
        discussions = [Discussion(topic=topic, expert_count=2) for topic in ("甲", "乙")]
        db.add_all(discussions); db.flush()
        participants = [Participant(discussion_id=d.id, role=ParticipantRole.EXPERT, name=f"{d.topic}专家",
                                    title="研究员", background="研究", stance="审慎", color="#123456")
                        for d in discussions]
        db.add_all(participants); db.flush()
        messages = [Message(discussion_id=d.id, speaker_id=p.id, sequence=1, content=f"{d.topic}证据")
                    for d, p in zip(discussions, participants)]
        db.add_all(messages); db.flush()
        save_insights(db, discussions[1].id, InsightBatch(items=[InsightCandidate(
            kind="consensus", content="乙讨论的已有共识", evidence_sequences=[1])]), [messages[1]])
        foreign_insight = db.scalar(select(DiscussionInsight).where(
            DiscussionInsight.discussion_id == discussions[1].id))
        save_insights(db, discussions[0].id, InsightBatch(items=[InsightCandidate(
            kind="consensus", content="试图更新另一讨论", evidence_sequences=[1],
            existing_insight_id=foreign_insight.id, concept_key="跨讨论")]), [messages[0]])
        first_id = discussions[0].id
    with SessionLocal() as db:
        assert db.scalars(select(DiscussionInsight).where(
            DiscussionInsight.discussion_id == first_id)).all() == []

def test_existing_insight_id_must_keep_its_kind():
    from backend.app.models import Participant, ParticipantRole
    with SessionLocal.begin() as db:
        d = Discussion(topic="类型校验", expert_count=2); db.add(d); db.flush()
        p = Participant(discussion_id=d.id, role=ParticipantRole.EXPERT, name="专家", title="研究员",
                        background="研究", stance="审慎", color="#123456"); db.add(p); db.flush()
        message = Message(discussion_id=d.id, speaker_id=p.id, sequence=1, content="有效证据")
        db.add(message); db.flush()
        save_insights(db, d.id, InsightBatch(items=[InsightCandidate(
            kind="consensus", content="已有共识内容", evidence_sequences=[1])]), [message])
        existing = db.scalar(select(DiscussionInsight).where(DiscussionInsight.discussion_id == d.id))
        save_insights(db, d.id, InsightBatch(items=[InsightCandidate(
            kind="disagreement", content="不能借用共识 ID 的分歧", evidence_sequences=[1],
            existing_insight_id=existing.id, concept_key="类型冲突")]), [message])
        did = d.id
    with SessionLocal() as db:
        rows = db.scalars(select(DiscussionInsight).where(DiscussionInsight.discussion_id == did)).all()
        assert len(rows) == 1 and rows[0].kind == InsightKind.CONSENSUS
        assert rows[0].content == "已有共识内容"

def test_updated_insight_is_visible_through_api_and_sse():
    from backend.app.models import Participant, ParticipantRole
    with SessionLocal.begin() as db:
        d = Discussion(topic="接口更新", expert_count=2, status=DiscussionStatus.COMPLETED)
        db.add(d); db.flush()
        p = Participant(discussion_id=d.id, role=ParticipantRole.EXPERT, name="专家", title="研究员",
                        background="研究", stance="审慎", color="#123456"); db.add(p); db.flush()
        messages = [Message(discussion_id=d.id, speaker_id=p.id, sequence=n, content=f"证据{n}") for n in (1, 2)]
        db.add_all(messages); db.flush()
        save_insights(db, d.id, InsightBatch(items=[InsightCandidate(
            kind="consensus", content="先试点再推广", evidence_sequences=[1], concept_key="推广节奏")]), messages)
        insight = db.scalar(select(DiscussionInsight).where(DiscussionInsight.discussion_id == d.id))
        save_insights(db, d.id, InsightBatch(items=[InsightCandidate(
            kind="consensus", content="应在试点评估后逐步推广", evidence_sequences=[2],
            existing_insight_id=insight.id, concept_key="推广节奏")]), messages)
        did, insight_id = d.id, insight.id
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/discussions/{did}/insights").json()
        wire = client.get(f"/api/v1/discussions/{did}/events").text
    assert len(payload) == 1 and payload[0]["id"] == insight_id and payload[0]["version"] == 2
    assert len(payload[0]["evidence_message_ids"]) == 2
    assert wire.count("event: insights.updated") == 2

def test_insight_prompt_exposes_existing_identity_without_extra_call():
    insight = DiscussionInsight(id=9, discussion_id=1, kind="disagreement",
                                content="岗位入口能否维持仍有分歧")
    system, user = insight_prompt("AI 编程工具", [], [], [insight])
    assert "existing_insight_id" in system and "concept_key" in system
    assert "ID=9" in user and "岗位入口能否维持仍有分歧" in user

def test_two_running_discussions_complete_independently():
    with TestClient(app) as client:
        ids = []
        for topic in ("并发甲", "并发乙"):
            did = client.post("/api/v1/discussions", json={"topic": topic}).json()["id"]
            client.post(f"/api/v1/discussions/{did}/roster")
            client.post(f"/api/v1/discussions/{did}/confirm")
            ids.append(did)
        for did in ids:
            assert client.post(f"/api/v1/discussions/{did}/start", json={"message_budget":7}).status_code == 202
        for _ in range(250):
            if all(client.get(f"/api/v1/discussions/{did}").json()["status"] == "completed" for did in ids): break
            time.sleep(.05)
        for did in ids:
            assert client.get(f"/api/v1/discussions/{did}").json()["status"] == "completed"
            assert len(client.get(f"/api/v1/discussions/{did}/transcript").json()) == 7
        with SessionLocal() as db:
            first = {m.id for m in db.scalars(select(Message).where(Message.discussion_id == ids[0])).all()}
            second = {m.id for m in db.scalars(select(Message).where(Message.discussion_id == ids[1])).all()}
            assert first.isdisjoint(second)

@pytest.mark.parametrize("budget", [18, 24])
def test_public_message_budget_reaches_limit_without_infinite_loop(budget, monkeypatch):
    class BudgetFake(FakeLLM):
        async def json(self, system, user, schema):
            if schema is Turn:
                ids = [int(x) for x in re.findall(r"^(\d+) .+（", user, re.MULTILINE)]
                number = int(re.search(r"已公开发言：(\d+)/", user).group(1))
                speaker = ids[0] if number == 0 else ids[1 + ((number - 1) % 4)]
                return Turn(speaker_id=speaker, action="open" if number == 0 else "answer",
                            text=f"第{number+1}条：回应已有观点并要求进一步核验。", focus="事实核验", finish=False)
            return await super().json(system, user, schema)

    app.state.llm = BudgetFake()
    original_sleep = asyncio.sleep
    async def fast_sleep(_):
        await original_sleep(0)
    monkeypatch.setattr("backend.app.discussion_service.asyncio.sleep", fast_sleep)
    with TestClient(app) as client:
        did = client.post("/api/v1/discussions", json={"topic": f"预算{budget}"}).json()["id"]
        assert client.post(f"/api/v1/discussions/{did}/roster").status_code == 200
        assert client.post(f"/api/v1/discussions/{did}/confirm").status_code == 200
        with SessionLocal.begin() as db:
            db.get(Discussion, did).status = DiscussionStatus.RUNNING
        asyncio.run(run_discussion(app, did, budget))
        detail = client.get(f"/api/v1/discussions/{did}").json()
        messages = client.get(f"/api/v1/discussions/{did}/transcript").json()
        assert detail["status"] == "completed"
        assert len(messages) == budget
        assert messages[-1]["action"] == "summary"
        assert all(len(message["content"]) <= 160 for message in messages[:-1])


def test_finish_requires_every_expert_to_participate():
    from backend.app.models import Participant, ParticipantRole
    people = [Participant(id=1, discussion_id=1, role=ParticipantRole.HOST, name="主持", title="主持",
                          background="主持", stance="中立", color="#111111")]
    people += [Participant(id=index, discussion_id=1, role=ParticipantRole.EXPERT, name=f"专家{index}",
                           title="专家", background="领域", stance=f"立场{index}", color=f"#{index:06x}")
               for index in range(2, 6)]
    messages = [Message(id=number, discussion_id=1, speaker_id=speaker, sequence=number, content=f"已有发言{number}。")
                for number, speaker in enumerate([1, 2, 3, 2], 1)]
    with pytest.raises(ModelError, match="所有专家至少发言一次"):
        validate_turn(Turn(speaker_id=4, action="add", text="补充一个不同条件。", finish=True),
                      people, messages, 18)


def test_start_rejects_budget_that_cannot_cover_roster():
    with TestClient(app) as client:
        did = client.post("/api/v1/discussions", json={"topic": "覆盖不足"}).json()["id"]
        client.post(f"/api/v1/discussions/{did}/roster")
        client.post(f"/api/v1/discussions/{did}/confirm")
        response = client.post(f"/api/v1/discussions/{did}/start", json={"message_budget": 5})
        assert response.status_code == 422
        assert client.get(f"/api/v1/discussions/{did}").json()["status"] == "confirmed"


def test_default_budget_has_dynamic_exchange_host_reentry_and_incremental_insights(monkeypatch):
    class QualityFake(FakeLLM):
        async def json(self, system, user, schema):
            if schema is Turn:
                ids = [int(x) for x in re.findall(r"^(\d+) .+（", user, re.MULTILINE)]
                number = int(re.search(r"已公开发言：(\d+)/", user).group(1))
                # Host re-enters at 6 and 11; expert 2 answers twice around expert 1's rebuttal.
                order = [0, 2, 1, 2, 3, 0, 4, 1, 3, 2, 0, 4, 2, 1, 3, 4, 2]
                speaker_index = order[number]
                if speaker_index == 0:
                    action = "open" if number == 0 else "moderate"
                else:
                    action = ["answer", "rebut", "add", "question", "interrupt"][number % 5]
                raised = action == "interrupt"
                return Turn(speaker_id=ids[speaker_index], action=action,
                            text=f"第{number + 1}条回应前文的证据边界，并提出新的可核验条件。",
                            focus=f"第{number + 1}阶段的公开核验重点", hand_raised=raised, finish=False)
            if schema is InsightBatch:
                sequences = [int(x) for x in re.findall(r"^#(\d+) ", user, re.MULTILINE)]
                latest = sequences[-1]
                consensus_id = re.search(r"ID=(\d+) kind=consensus", user)
                disagreement_id = re.search(r"ID=(\d+) kind=disagreement", user)
                return InsightBatch(items=[
                    InsightCandidate(kind="consensus", content=f"截至第{latest}条，各方同意先核验实际效果",
                                     evidence_sequences=sequences[-2:],
                                     existing_insight_id=int(consensus_id.group(1)) if consensus_id else None,
                                     concept_key="先核验实际效果"),
                    InsightCandidate(kind="disagreement", content=f"截至第{latest}条，实施边界仍有分歧",
                                     evidence_sequences=sequences[-3:-1],
                                     existing_insight_id=int(disagreement_id.group(1)) if disagreement_id else None,
                                     concept_key="实施边界"),
                ])
            return await super().json(system, user, schema)

    app.state.llm = QualityFake()
    original_sleep = asyncio.sleep
    async def fast_sleep(_):
        await original_sleep(0)
    monkeypatch.setattr("backend.app.discussion_service.asyncio.sleep", fast_sleep)
    with TestClient(app) as client:
        did = client.post("/api/v1/discussions", json={"topic": "默认预算质量验证"}).json()["id"]
        client.post(f"/api/v1/discussions/{did}/roster")
        client.post(f"/api/v1/discussions/{did}/confirm")
        with SessionLocal.begin() as db:
            db.get(Discussion, did).status = DiscussionStatus.RUNNING
        asyncio.run(run_discussion(app, did, 18))
        transcript = client.get(f"/api/v1/discussions/{did}/transcript").json()
        insights = client.get(f"/api/v1/discussions/{did}/insights").json()
        assert len(transcript) == 18
        assert transcript[-1]["action"] == "summary"
        speakers = [message["speaker_id"] for message in transcript[:-1]]
        assert speakers[:4] == [1, 3, 2, 3]
        assert speakers.count(1) >= 3
        assert set(speakers) == {1, 2, 3, 4, 5}
        assert len({message["content"] for message in transcript}) == len(transcript)
        assert {item["kind"] for item in insights} == {"consensus", "disagreement"}
        assert all(item["evidence_message_ids"] for item in insights)
        with SessionLocal() as db:
            events = db.scalars(select(DiscussionEvent).where(
                DiscussionEvent.discussion_id == did).order_by(DiscussionEvent.sequence)).all()
        assert len([item for item in events if item.event_type == "insights.updated"]) >= 4
        assert [item.sequence for item in events] == list(range(1, len(events) + 1))
        created_ids = [item.payload["message_id"] for item in events if item.event_type == "message.created"]
        assert len(created_ids) == len(set(created_ids)) == 18
