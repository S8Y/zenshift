"""ZenShift dashboard plugin backend.

Mounted by Hermes dashboard at /api/plugins/zenshift/.

Manages OpenCode Zen API key rotation — stores keys, rotates on configurable
strategies, blacklists dead keys for 24h, and auto-swaps on rate-limit errors.
"""
from __future__ import annotations

import json
import os
import time
import threading
from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, Query
except Exception:
    class APIRouter:
        def get(self, *a, **kw):
            return lambda fn: fn
        def post(self, *a, **kw):
            return lambda fn: fn
        def put(self, *a, **kw):
            return lambda fn: fn
        def delete(self, *a, **kw):
            return lambda fn: fn
    def Query(default=None, **kw):
        return default

router = APIRouter()

PLUGIN_VERSION = "0.1.0"

# ── State ──────────────────────────────────────────────────────────────────

ENV_VAR_NAME = "OPENCODE_ZEN_API_KEY"
STATE_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
STATE_FILE = str(STATE_DIR / "zenshift-state.json")

_keys: list[str] = []
_blacklist: dict[str, float] = {}
_active_key: str | None = None
_active_key_index: int = 0

_strategy: str = "session"
_interval_seconds: int = 600
_api_call_counter: int = 0
_api_calls_before_rotate: int = 1

_last_rotate_time: float = time.monotonic()
_total_rotations: int = 0
_total_blacklists: int = 0
_session_key_used: bool = False

_lock = threading.RLock()


def _load_env_file() -> dict[str, str]:
    env_path = STATE_DIR / ".env"
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            values[key.strip()] = value.strip().strip('"\'').strip()
        return values
    except Exception:
        return {}


def _write_env_file(updates: dict[str, str]) -> bool:
    env_path = STATE_DIR / ".env"
    current = _load_env_file()
    current.update(updates)
    try:
        lines = []
        existing_keys = set(updates.keys())
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                text = line.strip()
                if not text or text.startswith("#") or "=" not in text:
                    lines.append(line)
                    continue
                key = text.split("=", 1)[0].strip()
                if key in updates:
                    lines.append(f'{key}="{updates[key]}"')
                    existing_keys.discard(key)
                else:
                    lines.append(line)
        for key in existing_keys:
            lines.append(f'{key}="{updates[key]}"')
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False

_STATE_KEYS = {"_keys", "_active_key_index", "_strategy", "_interval_seconds",
    "_api_calls_before_rotate", "_total_rotations", "_total_blacklists"}

def _save_state() -> None:
    """Persist full plugin state to disk."""
    with _lock:
        try:
            state = {"v": 1, "saved_at": time.time()}
            bl = {}
            now_mono = time.monotonic()
            now_wall = time.time()
            for k, v in _blacklist.items():
                remaining = max(0, v - now_mono)
                bl[k] = now_wall + remaining if remaining > 0 else 0.0
            state["bl"] = bl
            state["ki"] = _active_key_index
            state["keys"] = list(_keys)
            state["str"] = _strategy
            state["int"] = _interval_seconds
            state["apic"] = _api_calls_before_rotate
            state["api_ct"] = _api_call_counter
            state["rot"] = _total_rotations
            state["nbl"] = _total_blacklists
            state["sk"] = _session_key_used
            p = Path(STATE_FILE)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(state))
        except Exception:
            pass  # best-effort save

def _load_state() -> None:
    """Restore full plugin state from disk."""
    global _keys, _active_key_index, _blacklist, _strategy
    global _interval_seconds, _api_calls_before_rotate, _api_call_counter
    global _total_rotations, _total_blacklists, _session_key_used
    p = Path(STATE_FILE)
    if not p.exists():
        return
    try:
        state = json.loads(p.read_text())
        if state.get("v") != 1:
            return
        now_mono = time.monotonic()
        now_wall = time.time()
        bl = {}
        for k, expires_wall in state.get("bl", {}).items():
            remaining = expires_wall - now_wall
            if remaining > 0:
                bl[k] = now_mono + remaining
        _blacklist = bl
        _keys = list(state.get("keys", []))
        _active_key_index = state.get("ki", 0)
        _strategy = state.get("str", "session")
        _interval_seconds = state.get("int", 600)
        _api_calls_before_rotate = state.get("apic", 10)
        _api_call_counter = state.get("api_ct", 0)
        _total_rotations = state.get("rot", 0)
        _total_blacklists = state.get("nbl", 0)
        _session_key_used = state.get("sk", False)
    except Exception:
        pass


def _apply_key(key: str | None) -> None:
    global _active_key
    if key is None:
        os.environ.pop(ENV_VAR_NAME, None)
        _active_key = None
    else:
        os.environ[ENV_VAR_NAME] = key
        _active_key = key
    if key:
        _write_env_file({ENV_VAR_NAME: key})


def _rotate_to_next() -> str | None:
    global _active_key_index, _last_rotate_time, _total_rotations, _session_key_used
    with _lock:
        if not _keys:
            return None
        now = time.monotonic()
        valid_set = {
            i for i, k in enumerate(_keys)
            if k not in _blacklist or _blacklist[k] <= now
        }
        if not valid_set:
            _active_key_index = 0
        elif _active_key_index in valid_set:
            sorted_valid = sorted(valid_set)
            cur = sorted_valid.index(_active_key_index)
            nxt = (cur + 1) % len(sorted_valid)
            _active_key_index = sorted_valid[nxt]
        else:
            sorted_valid = sorted(valid_set)
            nxt = None
            for idx in sorted_valid:
                if idx > _active_key_index:
                    nxt = idx
                    break
            if nxt is None:
                nxt = sorted_valid[0]
            _active_key_index = nxt
        key = _keys[_active_key_index]
        _apply_key(key)
        _last_rotate_time = time.monotonic()
        _total_rotations += 1
        _session_key_used = True
        _save_state()
        return key


def _init_from_env() -> None:
    global _active_key
    _load_state()
    current = os.environ.get(ENV_VAR_NAME) or _load_env_file().get(ENV_VAR_NAME)
    if current:
        _active_key = current
    elif _keys:
        idx = min(_active_key_index, len(_keys) - 1)
        _apply_key(_keys[idx])
        _last_rotate_time = time.monotonic()


# ── Error patterns ─────────────────────────────────────────────────────────

_RATELIMIT_PATTERNS = [
    "rate limit", "ratelimit", "rate_limit",
    "too many requests", "429",
    "quota exceeded", "insufficient_quota", "insufficient quota",
    "free tier limit", "free usage",
    "usage limit",
]

_DEAD_KEY_PATTERNS = [
    "invalid", "unauthorized", "forbidden", "not found",
    "key not found", "api key not", "no such api",
    "401", "403", "404",
    "expired", "revoked", "disabled",
    "permission denied", "access denied",
    "bad request", "invalid_api_key",
    "authentication failed", "auth failed",
    "key is dead", "dead key",
    "not a valid key",
]


def classify_error(error_text: str) -> str | None:
    lower = error_text.lower()
    for pat in _RATELIMIT_PATTERNS:
        if pat in lower:
            return "ratelimit"
    for pat in _DEAD_KEY_PATTERNS:
        if pat in lower:
            return "dead_key"
    return None


# ── API Routes ─────────────────────────────────────────────────────────────

@router.get("/status")
def get_status():
    with _lock:
        now = time.monotonic()
        active_env = os.environ.get(ENV_VAR_NAME, "")
        masked_key = active_env[:8] + "..." + active_env[-4:] if len(active_env) > 12 else ("(set)" if active_env else "(none)")
        blacklist_info = {}
        for key, expires in _blacklist.items():
            remaining = max(0, expires - now)
            blacklist_info[key[:8] + "..."] = {
                "remaining_seconds": int(remaining),
                "expired": remaining <= 0,
            }
        return {
            "version": PLUGIN_VERSION,
            "env_var": ENV_VAR_NAME,
            "active_key": masked_key,
            "active_key_index": _active_key_index,
            "total_keys": len(_keys),
            "valid_keys": sum(1 for k in _keys if k not in _blacklist or _blacklist[k] <= now),
            "blacklisted_count": sum(1 for k in _keys if k in _blacklist and _blacklist[k] > now),
            "blacklist": blacklist_info,
            "strategy": _strategy,
            "interval_seconds": _interval_seconds,
            "api_calls_before_rotate": _api_calls_before_rotate,
            "api_call_counter": _api_call_counter,
            "total_rotations": _total_rotations,
            "total_blacklists": _total_blacklists,
            "last_rotate_seconds_ago": int(now - _last_rotate_time),
            "session_key_used": _session_key_used,
        }


@router.get("/keys")
def list_keys():
    with _lock:
        now = time.monotonic()
        result = []
        for i, key in enumerate(_keys):
            masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "(short)"
            is_blacklisted = key in _blacklist and _blacklist[key] > now
            bl_rem = 0
            if is_blacklisted:
                bl_rem = int(_blacklist[key] - now)
            result.append({
                "index": i,
                "masked": masked,
                "active": key == _active_key,
                "blacklisted": is_blacklisted,
                "blacklist_remaining_seconds": bl_rem,
            })
        return {"keys": result, "total": len(result)}


@router.post("/keys")
def set_keys(data: dict):
    global _keys, _active_key_index
    raw_keys = data.get("keys", [])
    if not isinstance(raw_keys, list):
        return {"error": "keys must be an array of strings"}
    cleaned = [k.strip() for k in raw_keys if k.strip()]
    with _lock:
        _keys = cleaned
        _blacklist.clear()
        _active_key_index = 0
        _last_rotate_time = time.monotonic()
        if _keys:
            _apply_key(_keys[0])
    _save_state()
    return {"status": "ok", "count": len(cleaned)}


@router.post("/rotate")
def force_rotate():
    key = _rotate_to_next()
    return {
        "status": "ok" if key else "no_keys",
        "new_key_index": _active_key_index,
        "total_rotations": _total_rotations,
    }


@router.post("/config")
def set_config(data: dict):
    global _strategy, _interval_seconds, _api_calls_before_rotate, _api_call_counter
    with _lock:
        if "strategy" in data:
            val = str(data["strategy"]).strip()
            if val in ("session", "api_call", "timed"):
                _strategy = val
            else:
                return {"error": f"invalid strategy: {val}. Must be session, api_call, or timed"}
        if "interval_seconds" in data:
            _interval_seconds = max(30, int(data["interval_seconds"]))
        if "api_calls_before_rotate" in data:
            _api_calls_before_rotate = max(1, int(data["api_calls_before_rotate"]))
    _save_state()
    return get_status()


@router.post("/report-error")
def report_error(data: dict):
    error_text = data.get("error", "")
    if not error_text:
        return {"action": "none", "reason": "no error text provided"}
    classification = classify_error(error_text)
    if classification is None:
        return {"action": "none", "reason": "no actionable error pattern"}
    global _total_blacklists
    if classification == "ratelimit":
        with _lock:
            current_active = _active_key
        new_key = _rotate_to_next()
        return {
            "action": "rotated",
            "reason": "rate limit detected",
            "previous_key": current_active[:8] + "..." if current_active else None,
            "new_key_index": _active_key_index,
        }
    elif classification == "dead_key":
        with _lock:
            current_active = _active_key
            now = time.monotonic()
            if current_active:
                _blacklist[current_active] = now + 86400
                _total_blacklists += 1
        new_key = _rotate_to_next()
        return {
            "action": "blacklisted_and_rotated",
            "reason": "dead/invalid key detected",
            "blacklisted_key": current_active[:8] + "..." if current_active else None,
            "new_key_index": _active_key_index,
            "blacklist_duration_hours": 24,
        }
    return {"action": "none"}


@router.post("/report-tool-call")
def report_tool_call():
    global _api_call_counter
    if _strategy != "api_call":
        return {"status": "ignored", "reason": f"strategy is {_strategy}"}
    with _lock:
        _api_call_counter += 1
        should_rotate = _api_call_counter >= _api_calls_before_rotate
        if should_rotate:
            _api_call_counter = 0
    if should_rotate:
        _rotate_to_next()
        return {"status": "rotated", "counter_reset": True}
    return {"status": "ok", "counter": _api_call_counter}


@router.post("/reset-session")
def reset_session():
    global _session_key_used
    with _lock:
        _session_key_used = False
    if _strategy == "session":
        _rotate_to_next()
        _save_state()
        return {"status": "rotated_for_new_session", "strategy": "session"}
    return {"status": "ok", "strategy": _strategy}


@router.get("/check-timed")
def check_timed():
    if _strategy != "timed":
        return {"status": "ignored"}
    now = time.monotonic()
    with _lock:
        elapsed = now - _last_rotate_time
    if elapsed >= _interval_seconds:
        _rotate_to_next()
        return {"status": "rotated", "elapsed_seconds": int(elapsed), "interval": _interval_seconds}
    return {
        "status": "ok",
        "elapsed_seconds": int(elapsed),
        "remaining_seconds": int(_interval_seconds - elapsed),
    }


# ── Module-level init ──────────────────────────────────────────────────────
try:
    _init_from_env()
except Exception:
    pass
