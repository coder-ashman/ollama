import json
import shlex
import subprocess
from typing import Any, Dict, Tuple

from .config import ScriptConfig, load_settings
from .models import ScriptResult


def _render_args(params: Dict[str, Any]) -> Tuple[str, ...]:
    if not params:
        return tuple()
    # Preserve order of insertion (Python3.7+ dicts are ordered)
    return tuple(str(value) for value in params.values())


def _maybe_parse_json(payload: str) -> Any:
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def run_named_script(name: str, params: Dict[str, Any] | None = None) -> ScriptResult:
    settings = load_settings()
    if name not in settings.scripts:
        raise KeyError(f"Unknown script key: {name}")

    config: ScriptConfig = settings.scripts[name]
    params = params or {}

    if config.type in {"applescript", "jxa"}:
        if not config.path:
            raise ValueError(f"Script '{name}' is missing a path")
        interpreter = ["/usr/bin/osascript"]
        if config.type == "jxa":
            interpreter += ["-l", "JavaScript"]
        interpreter.append(str(config.path))
        interpreter += list(_render_args(params))
        cmd = interpreter
    elif config.type == "shortcut":
        shortcut_name = config.name or (config.path.name if config.path else name)
        cmd = ["/usr/bin/shortcuts", "run", shortcut_name]
        input_value = params.get("input")
        if input_value:
            cmd += ["--input", str(input_value)]
    else:
        raise ValueError(f"Unsupported script type: {config.type}")

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=config.timeout,
    )

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip() or None
    parsed = _maybe_parse_json(stdout)

    return ScriptResult(
        ok=proc.returncode == 0,
        stdout=stdout or None,
        stderr=stderr,
        parsed=parsed,
    )


__all__ = ["run_named_script"]
