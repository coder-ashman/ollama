from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class RunScriptRequest(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict)


class ScriptResult(BaseModel):
    ok: bool = True
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    parsed: Optional[Any] = None


class EmailDigestReport(BaseModel):
    unread: Any
    meetings: Any
    new_mail: Any


__all__ = ["RunScriptRequest", "ScriptResult", "EmailDigestReport"]
