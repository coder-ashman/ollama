from typing import Any, Dict, Optional

from .config import (
    CAP_DEEP,
    CAP_NORMAL,
    CAP_SHORT,
    CHARS_PER_TOKEN,
    FALLBACK_7B,
    INF,
    MODEL_DOWNGRADE,
    NORMAL_MAX,
    SHORT_MAX,
    SHORT_SENTENCES,
    TAIL_TOKENS,
)


DETAIL_KEYWORDS = {
    "example",
    "examples",
    "compare",
    "comparison",
    "contrast",
    "advantages",
    "disadvantages",
    "benefits",
    "best",
    "pros",
    "cons",
    "explain",
    "explanation",
    "why",
    "how",
    "detailed",
    "detail",
    "step-by-step",
}


def has_rag(body: Dict[str, Any]) -> bool:
    return bool(body.get("files") or body.get("collection") or body.get("collections"))


def _caps_with_mode(template: Dict[str, Any], mode: str) -> Dict[str, Any]:
    data = dict(template)
    data["_mode"] = mode
    return data


def _collapse_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _collapse_content(value.get("text") or "")
    if isinstance(value, list):
        return " ".join(_collapse_content(v) for v in value)
    return str(value or "")


def _chat_prompt_excerpt(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""

    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = _collapse_content(msg.get("content"))
            if content.strip():
                return content.strip()
    return " ".join(
        _collapse_content(m.get("content")) for m in messages if m.get("role") == "user"
    ).strip()


def _prompt_excerpt(body: Dict[str, Any]) -> str:
    prompt = (body.get("prompt") or "").strip()
    if prompt:
        return prompt
    return _chat_prompt_excerpt(body.get("messages"))


def choose_caps(body: Dict[str, Any]) -> Dict[str, Any]:
    if has_rag(body):
        return _caps_with_mode(CAP_DEEP, "deep")

    excerpt = _prompt_excerpt(body)
    n = len(excerpt.split())

    lower_excerpt = excerpt.lower()
    wants_detail = any(keyword in lower_excerpt for keyword in DETAIL_KEYWORDS)

    if n <= SHORT_MAX:
        if wants_detail:
            return _caps_with_mode(CAP_NORMAL, "normal")
        return _caps_with_mode(CAP_SHORT, "short")
    if n <= NORMAL_MAX:
        if wants_detail:
            return _caps_with_mode(CAP_DEEP, "deep")
        return _caps_with_mode(CAP_NORMAL, "normal")
    return _caps_with_mode(CAP_DEEP, "deep")


def safe_int(val: Any, default: Optional[int]) -> int:
    try:
        if val is None:
            return default  # type: ignore[return-value]
        return int(val)
    except Exception:
        return default  # type: ignore[return-value]


def extract_client_options(body: Dict[str, Any]) -> Dict[str, Any]:
    opts = dict(body.get("options") or {})

    if "stream" in body and "stream" not in opts:
        opts["stream"] = body["stream"]

    if "temperature" in body and ("temperature" not in opts or opts["temperature"] is None):
        opts["temperature"] = body["temperature"]
    if "stop" in body and ("stop" not in opts or opts["stop"] is None):
        opts["stop"] = body["stop"]

    if "max_tokens" in body and (safe_int(opts.get("num_predict"), None) is None):
        opts["num_predict"] = body["max_tokens"]

    if "num_predict" not in opts or opts["num_predict"] is None:
        opts.pop("num_predict", None)
    if "num_ctx" not in opts or opts["num_ctx"] is None:
        opts.pop("num_ctx", None)

    return opts


def clamp_options(chosen: Dict[str, Any], client: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(client)

    if "num_predict" in chosen:
        out["num_predict"] = min(
            safe_int(out.get("num_predict"), INF),
            safe_int(chosen["num_predict"], INF),
        )
    if "num_ctx" in chosen:
        out["num_ctx"] = min(
            safe_int(out.get("num_ctx"), INF),
            safe_int(chosen["num_ctx"], INF),
        )
    out.setdefault("temperature", chosen.get("temperature", 0.7))
    out.setdefault("repeat_penalty", chosen.get("repeat_penalty", 1.2))
    if "stop" in chosen and "stop" not in out:
        out["stop"] = chosen["stop"]
    return out


def maybe_downgrade_model(body: Dict[str, Any], chosen: Dict[str, Any]) -> Dict[str, Any]:
    is_short = safe_int(chosen.get("num_predict"), INF) <= 200
    rag = has_rag(body)
    model = (body.get("model") or "")
    if MODEL_DOWNGRADE and is_short and not rag and "14b" in model.lower():
        body["model"] = FALLBACK_7B
    return body


def should_trim_short(body: Dict[str, Any], chosen: Dict[str, Any], want_stream: bool) -> bool:
    if want_stream:
        return False
    if SHORT_SENTENCES <= 0:
        return False
    if chosen.get("_mode") != "short":
        return False
    if has_rag(body):
        return False
    return True


def compute_trim_config(
    body: Dict[str, Any],
    chosen: Dict[str, Any],
    want_stream: bool,
    client_opts: Dict[str, Any],
    base_predict: int,
) -> Optional[Dict[str, Any]]:
    if not should_trim_short(body, chosen, want_stream):
        return None

    client_limit = safe_int(client_opts.get("num_predict"), INF)
    tail_add = 0
    if TAIL_TOKENS > 0 and base_predict < INF:
        if client_limit == INF:
            tail_add = TAIL_TOKENS
        elif client_limit > base_predict:
            tail_add = min(TAIL_TOKENS, client_limit - base_predict)

    return {
        "sentences": max(1, SHORT_SENTENCES),
        "base_tokens": None if base_predict >= INF else base_predict,
        "tail_tokens": tail_add,
        "chars_per_token": max(0.1, CHARS_PER_TOKEN),
    }


__all__ = [
    "choose_caps",
    "extract_client_options",
    "clamp_options",
    "maybe_downgrade_model",
    "compute_trim_config",
    "has_rag",
    "safe_int",
]
