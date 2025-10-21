from typing import Any, Dict

from .config import EmailDigestConfig, load_settings
from .models import EmailDigestReport
from .script_runner import run_named_script


def _result_payload(result) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": result.ok,
        "stdout": result.stdout,
    }
    if result.parsed is not None:
        payload["parsed"] = result.parsed
    if result.stderr:
        payload["stderr"] = result.stderr
    return payload


def build_email_digest() -> EmailDigestReport:
    settings = load_settings()
    cfg: EmailDigestConfig | None = settings.reports.email_digest
    if not cfg:
        raise RuntimeError("Email digest report is not configured. Update actions.yml")

    unread = run_named_script(cfg.unread_key)
    meetings = run_named_script(cfg.meetings_key)
    new_mail = run_named_script(cfg.new_mail_key)

    return EmailDigestReport(
        unread=_result_payload(unread),
        meetings=_result_payload(meetings),
        new_mail=_result_payload(new_mail),
    )


__all__ = ["build_email_digest"]
