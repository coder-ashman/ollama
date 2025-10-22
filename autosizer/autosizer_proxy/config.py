import json
import os


def _load_cap(env_var: str, default_json: str) -> dict:
    return json.loads(os.environ.get(env_var, default_json))


OLLAMA = os.environ.get("TARGET_OLLAMA", "http://ollama:11434")
READ_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "300"))  # seconds
OSX_ACTIONS_BASE = os.environ.get("OSX_ACTIONS_BASE", "").rstrip("/")
OSX_ACTIONS_KEY = os.environ.get("OSX_ACTIONS_KEY", "")
OSX_ACTIONS_TIMEOUT = float(os.environ.get("OSX_ACTIONS_TIMEOUT", "90"))
OSX_ACTIONS_SELF = os.environ.get("OSX_ACTIONS_SELF", "")
OSX_ACTIONS_SELF_ALIASES = os.environ.get("OSX_ACTIONS_SELF_ALIASES", "")

SHORT_MAX = int(os.environ.get("SHORT_MAX_WORDS", "12"))
NORMAL_MAX = int(os.environ.get("NORMAL_MAX_WORDS", "60"))

CAP_SHORT = _load_cap(
    "CAP_SHORT",
    '{"num_predict":160,"num_ctx":1024,"temperature":0.6,"repeat_penalty":1.2,"stop":["<|im_end|>"]}',
)
CAP_NORMAL = _load_cap(
    "CAP_NORMAL",
    '{"num_predict":384,"num_ctx":2048,"temperature":0.7,"repeat_penalty":1.2, "stop": ["<|im_end|>"]}',
)
CAP_DEEP = _load_cap(
    "CAP_DEEP",
    '{"num_predict":768,"num_ctx":2048,"temperature":0.7,"repeat_penalty":1.1}',
)

TAIL_TOKENS = int(os.environ.get("TAIL_TOKENS", "0"))
CHARS_PER_TOKEN = float(os.environ.get("CHARS_PER_TOKEN", "4.0"))
SHORT_SENTENCES = int(os.environ.get("SHORT_SENTENCES", "2"))

MODEL_DOWNGRADE = os.getenv("MODEL_DOWNGRADE", "1") == "1"
FALLBACK_7B = os.getenv("FALLBACK_7B", "qwen2.5-7b-instruct-q5_K_M")

DEFAULT_SYSTEM_SHORT = os.getenv(
    "DEFAULT_SYSTEM_SHORT",
    "Be brief. Answer in 1-2 sentences in plain English. Do not write code unless explicitly asked. Do not start a new question or new turn. Finish your final sentence.",
)

INF = 10 ** 9

__all__ = [
    "OLLAMA",
    "READ_TIMEOUT",
    "OSX_ACTIONS_BASE",
    "OSX_ACTIONS_KEY",
    "OSX_ACTIONS_TIMEOUT",
    "OSX_ACTIONS_SELF",
    "OSX_ACTIONS_SELF_ALIASES",
    "SHORT_MAX",
    "NORMAL_MAX",
    "CAP_SHORT",
    "CAP_NORMAL",
    "CAP_DEEP",
    "TAIL_TOKENS",
    "CHARS_PER_TOKEN",
    "SHORT_SENTENCES",
    "MODEL_DOWNGRADE",
    "FALLBACK_7B",
    "DEFAULT_SYSTEM_SHORT",
    "INF",
]
