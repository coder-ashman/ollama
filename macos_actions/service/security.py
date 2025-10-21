from fastapi import Header, HTTPException

from .config import load_settings


def require_api_key(x_api_key: str | None = Header(None)) -> str:
    settings = load_settings()
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid api key")
    return x_api_key


__all__ = ["require_api_key"]
