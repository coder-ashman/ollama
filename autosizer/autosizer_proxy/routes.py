from flask import Blueprint

from .config import OLLAMA
from .proxy import handle_model_request, passthrough_request


routes = Blueprint("autosizer", __name__)


@routes.route("/healthz", methods=["GET"])
def health():
    return {"ok": True, "target": OLLAMA}


@routes.route("/api/generate", methods=["POST"])
def api_generate():
    return handle_model_request("/api/generate")


@routes.route("/api/chat", methods=["POST"])
def api_chat():
    return handle_model_request("/api/chat")


@routes.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def passthrough(path: str):
    return passthrough_request(path)


__all__ = ["routes"]
