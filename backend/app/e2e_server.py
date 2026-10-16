"""Isolated browser-test server; never uses the runtime database or real LLM."""
import asyncio
import os
import re
import tempfile
from pathlib import Path

from .llm import Guest, InsightBatch, InsightCandidate, ModelError, Roster, Turn


class BrowserFakeLLM:
    async def json(self, system, user, schema):
        topic_match = re.search(r"议题：([^\n]+)", user)
        topic = topic_match.group(1) if topic_match else "圆桌议题"
        if "故障测试" in topic:
            raise ModelError("受控模型故障（浏览器测试）")
        if schema is Roster:
            count = int(re.search(r"和 (\d+) 名专家", user).group(1))
            profiles = [
                ("教育研究员", "学习效果评估", "先小范围试点并追踪学习成效", "#C69CFF"),
                ("隐私工程师", "数据治理与合规", "必须先明确数据边界和退出机制", "#FFAD80"),
                ("一线教师", "课堂实践", "支持减负，但不能削弱师生互动", "#77D9B4"),
                ("学生代表", "学习体验", "要求透明说明并保留人工选择", "#F4D377"),
                ("产品负责人", "产品落地", "重视成本与维护责任", "#E899BC"),
                ("政策研究员", "公共政策", "主张阶段性审查", "#9EBBEF"),
            ]
            return Roster(
                host=Guest(name="林知远", title="圆桌主持人", background="公共议题主持", stance="中立追问，要求证据", color="#63B6E8"),
                experts=[Guest(name=f"测试专家{i+1}", title=title, background=background,
                               stance=stance, color=color) for i, (title, background, stance, color) in enumerate(profiles[:count])],
            )
        if schema is Turn:
            ids = [int(x) for x in re.findall(r"^(\d+) .+（", user, re.MULTILINE)]
            progress = re.search(r"已公开发言：(\d+)/(\d+)", user)
            uttered, budget = map(int, progress.groups())
            # Expert 2 responds twice, every expert participates, and the host re-enters.
            order = [0, 2, 1, 2, 3, 0, 4, 1, 3, 2, 0, 4, 2, 1, 3, 4, 2]
            index = order[min(uttered, len(order) - 1)]
            if index >= len(ids):
                index = 1
            await asyncio.sleep(0.15)
            if uttered == 0:
                action, text = "open", f"围绕{topic}，请先谈可验证的收益和风险。"
            elif index == 0:
                action, text = "moderate", f"第{uttered + 1}轮请回应刚才的分歧，并说明可核验条件。"
            else:
                actions = ["answer", "rebut", "add", "question", "interrupt"]
                action = actions[uttered % len(actions)]
                text = f"第{uttered + 1}轮回应前一观点：应同时核验学习效果、数据边界与退出机制。"
            full_budget = "完整预算" in topic
            earliest_finish = 3 if len(ids) == 3 else 6
            return Turn(speaker_id=ids[index], action=action, text=text, focus="核验收益与风险",
                        hand_raised=action == "interrupt" or uttered == 2,
                        finish=False if full_budget else uttered >= min(budget - 2, earliest_finish))
        if schema is InsightBatch:
            return InsightBatch(items=[
                InsightCandidate(kind="consensus", content="各方支持先试点并评估学习效果", evidence_sequences=[2, 4]),
                InsightCandidate(kind="disagreement", content="试点前是否必须完成数据边界约定仍有分歧", evidence_sequences=[2, 3]),
            ])
        from .discussion_service import Summary
        if schema is Summary:
            return Summary(text="主持人总结：各方认同应以小范围试点检验收益，但对数据边界的先后顺序仍有分歧。")
        raise AssertionError(schema)


def main():
    with tempfile.TemporaryDirectory(prefix="ai-panel-e2e-") as folder:
        os.environ["DATABASE_URL"] = "sqlite:///" + (Path(folder) / "e2e.db").as_posix()
        import uvicorn
        from .api import app
        from .database import engine
        app.state.llm = BrowserFakeLLM()
        try:
            uvicorn.run(app, host="127.0.0.1", port=8765, workers=1)
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
