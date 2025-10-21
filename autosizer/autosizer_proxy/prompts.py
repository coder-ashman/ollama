import logging
from typing import Any, Dict

from flask import current_app

from .caps import has_rag
from .config import DEFAULT_SYSTEM_SHORT

logger = logging.getLogger("autosizer.prompts")


def _get_logger():
    try:
        return current_app.logger
    except Exception:
        return logger


def inject_concise_system(body: Dict[str, Any], chosen: Dict[str, Any]) -> Dict[str, Any]:
    if chosen.get("_mode") != "short":
        return body
    if has_rag(body):
        return body

    msgs = body.get("messages")
    if isinstance(msgs, list) and msgs:
        if msgs[0].get("role") == "system":
            return body
        body["messages"] = [{"role": "system", "content": DEFAULT_SYSTEM_SHORT}] + msgs
        _get_logger().info("SYS: injected concise system (messages)")
    else:
        body["prompt"] = f"{DEFAULT_SYSTEM_SHORT}\n\n{(body.get('prompt') or '')}"
        _get_logger().info("SYS: injected concise system (prompt)")
    return body


__all__ = ["inject_concise_system"]
