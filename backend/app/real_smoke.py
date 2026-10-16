"""Optional live DeepSeek quality check, isolated from the runtime database.

Run from the repository root: python -m backend.app.real_smoke
"""
import os
import argparse
import tempfile
import time
from collections import Counter
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Isolated live DeepSeek verification")
    parser.add_argument("--experts", type=int, default=2, choices=range(2, 7))
    parser.add_argument("--budget", type=int, default=4, choices=range(4, 25))
    parser.add_argument("--timeout", type=int, default=600, help="maximum discussion wait in seconds")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ai-panel-live-", ignore_cleanup_errors=True) as folder:
        os.environ["DATABASE_URL"] = "sqlite:///" + (Path(folder) / "smoke.db").as_posix()
        from fastapi.testclient import TestClient
        from .api import app
        from .config import settings
        from .database import SessionLocal, engine
        from .models import DiscussionEvent
        from sqlalchemy import select

        def finish(code):
            engine.dispose()
            return code

        print(f"配置：密钥={'已加载' if bool(settings.openai_api_key) else '缺失'}，模型={settings.openai_model}")
        if not settings.openai_api_key:
            return finish(2)
        with TestClient(app) as client:
            created = client.post("/api/v1/discussions", json={
                "topic": "高校是否应该全面推广生成式 AI 助教？",
                "expert_count": args.experts,
            })
            created.raise_for_status()
            did = created.json()["id"]
            roster_started_at = time.perf_counter()
            roster = client.post(f"/api/v1/discussions/{did}/roster")
            roster_seconds = time.perf_counter() - roster_started_at
            if roster.status_code != 200:
                print(f"真实阵容生成失败：HTTP {roster.status_code}，{roster.json().get('detail', '未知错误')}")
                return finish(1)
            print(f"真实阵容生成成功：{len(roster.json())} 位参与者，耗时={roster_seconds:.1f}s")
            client.post(f"/api/v1/discussions/{did}/confirm").raise_for_status()
            started_at = time.perf_counter()
            client.post(f"/api/v1/discussions/{did}/start", json={"message_budget": args.budget}).raise_for_status()
            deadline = time.monotonic() + args.timeout
            while True:
                detail = client.get(f"/api/v1/discussions/{did}").json()
                if detail["status"] in ("completed", "failed", "stopped"):
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(1)
            messages = client.get(f"/api/v1/discussions/{did}/transcript").json()
            insights = client.get(f"/api/v1/discussions/{did}/insights").json()
            elapsed = time.perf_counter() - started_at
            print(f"真实讨论：状态={detail['status']}，发言={len(messages)}，洞见={len(insights)}，总结={'有' if detail.get('summary') else '无'}，耗时={elapsed:.1f}s")
            participants = {person["id"]: person for person in roster.json()}
            distribution = Counter(participants[item["speaker_id"]]["name"] for item in messages)
            print("发言分布：" + ("，".join(f"{name}={count}" for name, count in distribution.items()) or "无"))
            print("实际调度顺序：" + (" → ".join(
                f"{item['sequence']:02d}:{participants[item['speaker_id']]['name']}({item.get('action') or 'unknown'})"
                for item in messages) or "无"))
            for item in messages:
                print(f"发言#{item['sequence']} {participants[item['speaker_id']]['name']} [{item.get('action')}]：{item['content']}")
            for item in insights:
                print(f"洞见[{item['kind']}] v{item['version']} 证据={item['evidence_message_ids']}：{item['content']}")
            with SessionLocal() as db:
                persisted_events = db.scalars(select(DiscussionEvent).where(
                    DiscussionEvent.discussion_id == did).order_by(DiscussionEvent.sequence)).all()
            message_count = 0
            insight_timing = []
            for item in persisted_events:
                if item.event_type == "message.created":
                    message_count += 1
                elif item.event_type == "insights.updated":
                    insight_timing.append((item.sequence, message_count))
            print("洞见更新时间：" + ("，".join(f"事件#{event_seq}/发言后{count}" for event_seq, count in insight_timing) or "无"))
            usage = getattr(app.state.llm, "usage", {})
            print("Token 用量：" + (", ".join(f"{key}={value}" for key, value in usage.items()) if usage else "服务未返回"))
            calls = getattr(app.state.llm, "calls", [])
            print(f"模型 API 请求次数：{getattr(app.state.llm, 'request_count', len(calls))}")
            if calls:
                print("单次调用：" + "，".join(
                    f"#{index + 1} {call['schema']}/尝试{call['attempt']}/{call['status']}/{call['seconds']:.1f}s"
                    for index, call in enumerate(calls)))
                durations = [call["seconds"] for call in calls]
                print(f"调用耗时统计：平均={sum(durations) / len(durations):.1f}s，最大={max(durations):.1f}s，总计={sum(durations):.1f}s")
            print(f"主持总结：{detail.get('summary') or '无'}")
            if detail["status"] != "completed":
                with SessionLocal() as db:
                    failure = db.scalar(select(DiscussionEvent).where(
                        DiscussionEvent.discussion_id == did,
                        DiscussionEvent.event_type == "discussion.error").order_by(DiscussionEvent.sequence.desc()))
                    if failure:
                        print(f"失败原因：{failure.payload.get('message', '未知错误')}")
                if detail["status"] == "running":
                    print(f"达到 {args.timeout}s 等待上限，主动停止并保留以上部分结果。")
                    client.post(f"/api/v1/discussions/{did}/stop")
                return finish(1)
            wire = client.get(f"/api/v1/discussions/{did}/events").text
            events_ok = all(name in wire for name in (
                "event: message.created", "event: insights.updated", "event: discussion.summary"))
            print(f"SSE 回放={'通过' if events_ok else '失败'}，洞见类型={','.join(sorted({x['kind'] for x in insights}))}")
            if not events_ok:
                return finish(1)
            return finish(0)


if __name__ == "__main__":
    raise SystemExit(main())
