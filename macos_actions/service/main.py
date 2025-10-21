from fastapi import Body, Depends, FastAPI

from .aggregators import build_email_digest
from .config import load_settings
from .models import EmailDigestReport, RunScriptRequest
from .script_runner import run_named_script
from .security import require_api_key


def create_app() -> FastAPI:
    app = FastAPI(title="macOS Actions Gateway", version="0.1.0")

    @app.get("/health")
    def healthcheck():
        settings = load_settings()
        return {
            "ok": True,
            "scripts": list(settings.scripts.keys()),
            "reports": [
                name
                for name, value in {
                    "email_digest": settings.reports.email_digest,
                }.items()
                if value is not None
            ],
        }

    @app.post("/scripts/{name}/run")
    def run_script(
        name: str,
        payload: RunScriptRequest = Body(default_factory=RunScriptRequest),
        api_key: str = Depends(require_api_key),
    ):
        _ = api_key
        result = run_named_script(name, payload.params)
        return result.dict()

    @app.post("/reports/email-digest", response_model=EmailDigestReport)
    def email_digest(api_key: str = Depends(require_api_key)):
        _ = api_key
        report = build_email_digest()
        return report

    return app


app = create_app()


__all__ = ["create_app", "app"]
