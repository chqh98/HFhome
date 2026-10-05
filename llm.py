"""AI(LLM) 호출 모듈. OpenAI / Claude(Anthropic) / Gemini 중 하나를 골라 쓴다.

설정은 Streamlit Secrets(.streamlit/secrets.toml 또는 배포 화면의 Secrets)에 넣는다.
    LLM_PROVIDER = "gemini"      # gemini | openai | anthropic
    LLM_API_KEY  = "발급받은 키"
    LLM_MODEL    = "gemini-2.5-flash"   # 생략하면 아래 기본 모델
외부 패키지 없이 표준 라이브러리(urllib)로 호출해서 SDK 버전 문제가 없다.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-haiku-4-5-20251001",
}


class LLMError(RuntimeError):
    pass


def _post(url: str, headers: dict, body: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise LLMError(f"AI 서비스 오류 ({e.code}): {detail}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"AI 서비스에 연결하지 못했어요: {e.reason}") from e


def chat(system: str, user: str, *, provider: str, api_key: str, model: str | None = None,
         want_json: bool = False, temperature: float = 0.2, max_tokens: int = 2000) -> str:
    """system 지시문과 user 메시지를 보내고 답변 텍스트를 돌려준다."""
    provider = (provider or "").lower().strip()
    model = model or DEFAULT_MODELS.get(provider)
    if not api_key:
        raise LLMError("API 키가 설정되지 않았어요.")

    if provider == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if want_json:
            cfg["responseMimeType"] = "application/json"
        data = _post(url, {"x-goog-api-key": api_key}, {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": cfg,
        })
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as e:
            raise LLMError(f"Gemini 응답을 읽지 못했어요: {str(data)[:200]}") from e

    if provider == "openai":
        body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if want_json:
            body["response_format"] = {"type": "json_object"}
        data = _post("https://api.openai.com/v1/chat/completions", {"Authorization": f"Bearer {api_key}"}, body)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"OpenAI 응답을 읽지 못했어요: {str(data)[:200]}") from e

    if provider == "anthropic":
        data = _post("https://api.anthropic.com/v1/messages",
                     {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                     {"model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                      "messages": [{"role": "user", "content": user}]})
        try:
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise LLMError(f"Claude 응답을 읽지 못했어요: {str(data)[:200]}") from e

    raise LLMError(f"알 수 없는 AI 서비스: {provider} (gemini / openai / anthropic 중 하나)")


def parse_json(text: str) -> dict:
    """```json 코드블록이나 앞뒤 설명이 섞여 와도 JSON 객체만 꺼낸다."""
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise LLMError("AI가 JSON 형식으로 답하지 않았어요.")
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"AI 답변의 JSON을 읽지 못했어요: {e}") from e
