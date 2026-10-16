"""Small OpenAI-compatible adapter. No model response is trusted until validated."""
import json
import httpx
from pydantic import BaseModel, Field, ValidationError
from .config import settings


class ModelError(Exception):
    pass


class Guest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=160)
    background: str = Field(min_length=1)
    stance: str = Field(min_length=1)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class Roster(BaseModel):
    host: Guest
    experts: list[Guest]


class Turn(BaseModel):
    speaker_id: int
    action: str = Field(pattern=r"^(open|invite|answer|add|rebut|question|interrupt|moderate)$")
    # The public 160-character limit is enforced after sentence compaction.
    # A longer model draft must survive schema parsing to reach that step.
    text: str = Field(min_length=2, max_length=2000)
    focus: str = Field(default="", max_length=120)
    hand_raised: bool = False
    finish: bool = False


class InsightCandidate(BaseModel):
    kind: str = Field(pattern=r"^(consensus|disagreement)$")
    content: str = Field(min_length=5, max_length=220)
    evidence_sequences: list[int] = Field(min_length=1, max_length=4)


class InsightBatch(BaseModel):
    items: list[InsightCandidate] = Field(max_length=4)


class OpenAICompatibleLLM:
    async def json(self, system: str, user: str, schema: type[BaseModel]):
        if not settings.openai_api_key:
            raise ModelError("后端未配置 OPENAI_API_KEY")
        endpoint = settings.openai_base_url.rstrip("/") + "/chat/completions"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        async with httpx.AsyncClient(timeout=50) as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        endpoint,
                        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                        json={"model": settings.openai_model, "messages": messages,
                              "response_format": {"type": "json_object"}, "temperature": 0.6},
                    )
                    response.raise_for_status()
                    raw = response.json()["choices"][0]["message"]["content"]
                    return schema.model_validate(json.loads(raw))
                except (json.JSONDecodeError, ValidationError, KeyError, IndexError) as exc:
                    if attempt:
                        fields = ",".join(".".join(map(str, error["loc"])) for error in exc.errors()) if isinstance(exc, ValidationError) else "JSON"
                        raise ModelError(f"模型连续两次返回不符合结构要求的内容（{fields}）") from exc
                    messages.extend([{"role": "assistant", "content": raw if "raw" in locals() else ""},
                                     {"role": "user", "content": "仅返回符合指定 JSON 结构的对象，纠正上次格式错误。"}])
                except httpx.HTTPStatusError as exc:
                    raise ModelError(f"模型接口 HTTP {exc.response.status_code}；请检查模型名称、密钥和服务地址") from exc
                except httpx.RequestError as exc:
                    raise ModelError(f"模型接口连接失败：{type(exc).__name__}") from exc


def get_llm(app):
    return getattr(app.state, "llm", None) or OpenAICompatibleLLM()
