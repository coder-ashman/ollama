import logging
import re
from typing import Any, Dict, Optional

from flask import current_app

from .config import CHARS_PER_TOKEN, SHORT_SENTENCES

logger = logging.getLogger("autosizer.finishers")

SENT_SPLIT = re.compile(r'(?<=[\.!\?。！？])\s+')
BOUNDARY_PUNCT = re.compile(r"([\.\!\?。！？]+[\)\]\'\"]?)\s*$")
END_PUNCT = (".", "?", "!", "。", "！", "？", "...")


def _get_logger():
    try:
        return current_app.logger
    except Exception:
        return logger


def keep_first_sentences(text: str, n: int = 2) -> str:
    parts = SENT_SPLIT.split(text.strip())
    if not parts:
        return text
    return " ".join(parts[:n])


def trim_to_boundary(text: str) -> str:
    text = (text or "").rstrip()
    if not text:
        return text

    for marker in ("```", "\n\n"):
        idx = text.find(marker)
        if idx != -1:
            return text[:idx].rstrip() or text

    match = BOUNDARY_PUNCT.search(text)
    if match:
        return text[: match.end(1)].rstrip()

    for punct in ".?!。！？":
        idx = text.rfind(punct)
        if idx != -1:
            return text[: idx + 1].rstrip()

    return text


def finish_short_text(text: str, config: Dict[str, Any]) -> str:
    raw = (text or "").strip()
    if not raw:
        return text

    base_tokens = config.get("base_tokens") or 0
    tail_tokens = config.get("tail_tokens") or 0
    chars_per_token = config.get("chars_per_token") or CHARS_PER_TOKEN
    sentences = config.get("sentences") or SHORT_SENTENCES

    if base_tokens > 0 and chars_per_token > 0:
        window_tokens = base_tokens + max(0, tail_tokens)
        max_chars = int(window_tokens * chars_per_token)
        if max_chars > 0 and len(raw) > max_chars:
            raw = raw[:max_chars].rstrip()

    trimmed = keep_first_sentences(raw, max(1, sentences)).strip()

    if tail_tokens > 0:
        bounded = trim_to_boundary(trimmed)
        if bounded:
            trimmed = bounded

    return trimmed or text


def apply_short_response_finisher(payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
    changed = False

    if "response" in payload and isinstance(payload["response"], str):
        finished = finish_short_text(payload["response"], config)
        if finished != payload["response"]:
            payload["response"] = finished
            changed = True

    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        finished = finish_short_text(message["content"], config)
        if finished != message["content"]:
            message["content"] = finished
            changed = True

    if changed:
        _get_logger().info(
            "FINISH short reply sentences=%s tail=%s",
            config.get("sentences"),
            config.get("tail_tokens"),
        )
    return changed


def apply_length_cutoff_finisher(payload: Dict[str, Any]) -> bool:
    if payload.get("done_reason") != "length":
        return False

    changed = False

    def _tidy(value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return value
        trimmed = trim_to_boundary(value)
        if trimmed != value:
            return f"{trimmed} ..."
        if trimmed and not trimmed.endswith(END_PUNCT):
            return f"{trimmed} ..."
        return trimmed

    if "response" in payload:
        cleaned = _tidy(payload.get("response"))
        if cleaned is not None and cleaned != payload.get("response"):
            payload["response"] = cleaned
            changed = True

    message = payload.get("message")
    if isinstance(message, dict) and "content" in message:
        cleaned = _tidy(message.get("content"))
        if cleaned is not None and cleaned != message.get("content"):
            message["content"] = cleaned
            changed = True

    if changed:
        _get_logger().info("FINISH cutoff done_reason=length")
    return changed


__all__ = [
    "keep_first_sentences",
    "trim_to_boundary",
    "finish_short_text",
    "apply_short_response_finisher",
    "apply_length_cutoff_finisher",
    "END_PUNCT",
]
