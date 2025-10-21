from flask import request


def register_request_logging(app):
    @app.before_request
    def _log_in():
        try:
            payload = request.get_json(silent=True) or {}
            app.logger.info(
                "IN %s %s model=%s stream=%s max_tokens=%s opts=%s",
                request.method,
                request.path,
                payload.get("model"),
                payload.get("stream") or (payload.get("options") or {}).get("stream"),
                payload.get("max_tokens"),
                {
                    k: (payload.get("options") or {}).get(k)
                    for k in ("num_predict", "num_ctx", "temperature")
                },
            )
        except Exception:
            app.logger.info("IN %s %s (no json)", request.method, request.path)

    @app.after_request
    def _log_out(resp):
        app.logger.info("OUT %s %s %s", request.method, request.path, resp.status_code)
        return resp


__all__ = ["register_request_logging"]
