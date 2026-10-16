import asyncio
import re
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.app.api import app
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import Discussion, DiscussionStatus, Message, DiscussionEvent, DiscussionInsight
from backend.app.llm import Guest, Roster, Turn, InsightBatch, InsightCandidate, ModelError
from backend.app.discussion_service import run_discussion, Summary, compact_public_text
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
            # Host, expert 2, expert 1, expert 2: a deliberate non-round-robin interaction.
            sequence = [(ids[0], "open"), (ids[2], "answer"), (ids[1], "rebut"), (ids[2], "add")]
            speaker, action = sequence[min(turn_number - 1, 3)]
            return Turn(speaker_id=speaker, action=action,
                        text=f"第{turn_number}轮：针对上一观点提出具体条件。", focus="讨论实施条件",
                        hand_raised=turn_number == 3, finish=turn_number == 4)
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
        asyncio.run(run_discussion(app, did, 5))
        detail = client.get(f"/api/v1/discussions/{did}").json()
        with SessionLocal() as db:
            failure = db.scalar(select(DiscussionEvent).where(DiscussionEvent.discussion_id == did,
                DiscussionEvent.event_type == "discussion.error"))
        assert detail["status"] == "completed" and detail["summary"], failure.payload if failure else None
        messages = client.get(f"/api/v1/discussions/{did}/transcript").json()
        assert len(messages) == 5
        assert [m["speaker_id"] for m in messages[:4]] == [1, 3, 2, 3]
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
        assert client.post(f"/api/v1/discussions/{did}/start", json={"message_budget":5}).status_code == 202
        assert client.post(f"/api/v1/discussions/{did}/start").status_code == 409
        for _ in range(100):
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
        assert client.post(f"/api/v1/discussions/{did}/start", json={"message_budget":4}).status_code == 202
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

def test_insight_updates_are_bounded_and_keep_evidence():
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
        assert any(row.version == 2 and row.content == "更新后的新共识" for row in rows)
        assert all(len(row.evidence) == 2 for row in rows)

def test_two_running_discussions_complete_independently():
    with TestClient(app) as client:
        ids = []
        for topic in ("并发甲", "并发乙"):
            did = client.post("/api/v1/discussions", json={"topic": topic}).json()["id"]
            client.post(f"/api/v1/discussions/{did}/roster")
            client.post(f"/api/v1/discussions/{did}/confirm")
            ids.append(did)
        for did in ids:
            assert client.post(f"/api/v1/discussions/{did}/start", json={"message_budget":5}).status_code == 202
        for _ in range(100):
            if all(client.get(f"/api/v1/discussions/{did}").json()["status"] == "completed" for did in ids): break
            time.sleep(.05)
        for did in ids:
            assert client.get(f"/api/v1/discussions/{did}").json()["status"] == "completed"
            assert len(client.get(f"/api/v1/discussions/{did}/transcript").json()) == 5
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
                speaker = ids[0] if number == 0 else ids[1 + (number % 2)]
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
