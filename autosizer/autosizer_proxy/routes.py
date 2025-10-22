from flask import Blueprint, Response, request

from .config import OLLAMA
from .proxy import handle_model_request, passthrough_request
from .macos_actions import call_script, maybe_handle_chat


routes = Blueprint("autosizer", __name__)


@routes.route("/healthz", methods=["GET"])
def health():
    return {"ok": True, "target": OLLAMA}


@routes.route("/api/generate", methods=["POST"])
def api_generate():
    return handle_model_request("/api/generate")


@routes.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(force=True, silent=True) or {}
    handled = maybe_handle_chat(body)
    if handled is not None:
        return handled
    return handle_model_request("/api/chat")


@routes.route("/tool/osx/<script>/run", methods=["POST"])
def osx_script(script: str):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return Response('{"error":"payload must be JSON object"}', status=400, mimetype="application/json")
    return call_script(script, payload)


@routes.route("/tool/osx/run", methods=["POST"])
def osx_script_body():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return Response('{"error":"body must be JSON object"}', status=400, mimetype="application/json")

    script = body.get("script") or body.get("action")
    if not isinstance(script, str) or not script:
        return Response('{"error":"missing script"}', status=400, mimetype="application/json")

    payload = body.get("payload") or body.get("body") or {}
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return Response('{"error":"payload must be JSON object"}', status=400, mimetype="application/json")

    return call_script(script, payload)


@routes.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def passthrough(path: str):
    return passthrough_request(path)


__all__ = ["routes"]
