import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

import yaml
from pydantic import BaseModel, Field, validator


class ScriptConfig(BaseModel):
    """Definition of a whitelisted automation action."""

    type: str = Field(..., regex=r"^(applescript|jxa|shortcut|shell)$")
    path: Optional[Path] = None
    name: Optional[str] = None
    timeout: int = Field(30, ge=1, le=600)

    @validator("path", pre=True)
    def _expand_path(cls, value):  # type: ignore[override]
        if value is None:
            return value
        return Path(os.path.expanduser(str(value))).resolve()


class EmailDigestConfig(BaseModel):
    unread_key: str = Field(..., description="Script key for unread emails from previous day")
    meetings_key: str = Field(..., description="Script key for today's meetings")
    new_mail_key: str = Field(..., description="Script key for new mail polling")


class ReportsConfig(BaseModel):
    email_digest: Optional[EmailDigestConfig] = None


class Settings(BaseModel):
    api_key: str
    scripts: Dict[str, ScriptConfig]
    reports: ReportsConfig = ReportsConfig()


DEFAULT_CONFIG_LOCATIONS = (
    Path(os.getenv("OSX_ACTIONS_CONFIG", "")),
    Path.home() / "Library" / "Application Support" / "macos_actions" / "actions.yml",
    Path(__file__).resolve().parent.parent / "config" / "actions.example.yml",
)


def _load_yaml_config() -> Dict:
    for candidate in DEFAULT_CONFIG_LOCATIONS:
        if candidate and candidate.exists():
            with candidate.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            return data
    raise FileNotFoundError(
        "No configuration file found. Set OSX_ACTIONS_CONFIG or place actions.yml in "
        "~/Library/Application Support/macos_actions/."
    )


def _load_api_key() -> str:
    key = os.getenv("OSX_ACTIONS_KEY")
    if key:
        return key

    service_name = os.getenv("OSX_ACTIONS_KEYCHAIN_NAME", "osx_actions_key")
    try:
        proc = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", service_name, "-w"],
            check=True,
            capture_output=True,
            text=True,
        )
        key = proc.stdout.strip()
        if key:
            return key
    except subprocess.CalledProcessError:
        pass

    raise RuntimeError(
        "Automation API key not found. Set OSX_ACTIONS_KEY env var or store it in Keychain "
        "with service name 'osx_actions_key' (customizable via OSX_ACTIONS_KEYCHAIN_NAME)."
    )


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    raw = _load_yaml_config()
    scripts = raw.get("scripts") or {}
    reports = raw.get("reports") or {}

    settings = Settings(
        api_key=_load_api_key(),
        scripts={name: ScriptConfig(**cfg) for name, cfg in scripts.items()},
        reports=ReportsConfig(**reports),
    )
    return settings


__all__ = ["Settings", "ScriptConfig", "ReportsConfig", "load_settings"]
