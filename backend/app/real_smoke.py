"""Optional low-budget live DeepSeek check, isolated from the runtime database.

Run from the repository root: python -m backend.app.real_smoke
"""
import os
import tempfile
import time
from pathlib import Path


def main():
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
                "topic": "高校使用生成式 AI 助教，应如何平衡教学效率、学习质量与隐私？",
                "expert_count": 2,
            })
            created.raise_for_status()
            did = created.json()["id"]
            roster = client.post(f"/api/v1/discussions/{did}/roster")
            if roster.status_code != 200:
                print(f"真实阵容生成失败：HTTP {roster.status_code}，{roster.json().get('detail', '未知错误')}")
                return finish(1)
            print(f"真实阵容生成成功：{len(roster.json())} 位参与者")
            client.post(f"/api/v1/discussions/{did}/confirm").raise_for_status()
            client.post(f"/api/v1/discussions/{did}/start", json={"message_budget": 4}).raise_for_status()
            for _ in range(180):
                detail = client.get(f"/api/v1/discussions/{did}").json()
                if detail["status"] in ("completed", "failed", "stopped"):
                    break
                time.sleep(1)
            messages = client.get(f"/api/v1/discussions/{did}/transcript").json()
            insights = client.get(f"/api/v1/discussions/{did}/insights").json()
            print(f"真实短讨论：状态={detail['status']}，发言={len(messages)}，洞见={len(insights)}，总结={'有' if detail.get('summary') else '无'}")
            if detail["status"] != "completed":
                with SessionLocal() as db:
                    failure = db.scalar(select(DiscussionEvent).where(
                        DiscussionEvent.discussion_id == did,
                        DiscussionEvent.event_type == "discussion.error").order_by(DiscussionEvent.sequence.desc()))
                    if failure:
                        print(f"失败原因：{failure.payload.get('message', '未知错误')}")
                if detail["status"] == "running":
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
