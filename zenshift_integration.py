#!/usr/bin/env python3
"""ZenShift Integration — fully automatic key rotation for Hermes Agent."""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger("zenshift.integration")

# Module state
_integration_installed = False
_background_thread: threading.Thread | None = None
_stop_event = threading.Event()
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
_ENV_PATH = _HERMES_HOME / ".env"
_ENV_VAR = "OPENCODE_ZEN_API_KEY"


def _read_env_file() -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        if _ENV_PATH.exists():
            for line in _ENV_PATH.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip()
    except OSError as exc:
        logger.warning("Failed to read %s: %s", _ENV_PATH, exc)
    return env


def _write_env_file(updates: dict[str, str]) -> bool:
    """Update specific keys in .env, preserving all others."""
    try:
        current_env = _read_env_file()
        current_env.update(updates)
        lines = []
        existing_keys = set(updates.keys())
        if _ENV_PATH.exists():
            for line in _ENV_PATH.read_text().splitlines():
                stripped = line.strip()
                if "=" not in stripped or stripped.startswith("#"):
                    lines.append(line)
                    continue
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    lines.append(f'{key}="{updates[key]}"')
                    existing_keys.discard(key)
                else:
                    lines.append(line)
        for key in existing_keys:
            lines.append(f'{key}="{updates[key]}"')
        _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    except OSError as exc:
        logger.warning("Failed to write %s: %s", _ENV_PATH, exc)
        return False


def _get_plugin_api():
    """Try to import the dashboard plugin_api module directly."""
    try:
        spec = None
        dashboard_dir = _HERMES_HOME / "plugins" / "zenshift" / "dashboard"
        api_path = dashboard_dir / "plugin_api.py"
        if api_path.exists():
            import importlib.util
            mod_name = "zenshift_dashboard_api"
            spec = importlib.util.spec_from_file_location(mod_name, str(api_path))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
                return mod
    except Exception:
        pass
    return None


def _install_error_feed():
    try:
        from agent import error_classifier as _ec
    except ImportError:
        logger.debug("ZenShift: agent.error_classifier not available")
        return
    if not hasattr(_ec, "classify_api_error"):
        logger.debug("ZenShift: no classify_api_error to patch")
        return

    _orig = _ec.classify_api_error

    def _patched(error, **kwargs):
        provider = kwargs.get("provider", "").strip().lower()
        if "opencode" in provider or provider in ("zen",):
            try:
                api = _get_plugin_api()
                if api is not None:
                    result = api.report_error({"error": str(error)})
                    action = result.get("action", "none")
                    if action in ("rotated", "blacklisted_and_rotated"):
                        logger.info("ZenShift: %s on %s", action, result.get("reason", "error"))
            except Exception:
                pass
        return _orig(error, **kwargs)

    _ec.classify_api_error = _patched
    logger.info("ZenShift: patched classify_api_error for OpenCode/Zen providers")


def _install_client_key_injection():
    try:
        import run_agent as _ra
    except ImportError:
        logger.debug("ZenShift: run_agent not available")
        return
    cls = getattr(_ra, "AIAgent", None)
    if cls is None:
        return
    orig = getattr(cls, "_create_request_openai_client", None)
    if orig is None:
        return

    def _patched(self, **kwargs):
        _ensure_key_active()
        try:
            api = _get_plugin_api()
            if api is not None:
                api.report_tool_call({})
        except Exception:
            pass
        return orig(self, **kwargs)

    setattr(cls, "_create_request_openai_client", _patched)
    logger.info("ZenShift: patched _create_request_openai_client")


def _ensure_key_active():
    try:
        api = _get_plugin_api()
        if api is None:
            return
        api.check_timed()
        if api._active_key and os.environ.get(_ENV_VAR) != api._active_key:
            os.environ[_ENV_VAR] = api._active_key
            _write_env_file({_ENV_VAR: api._active_key})
    except Exception as exc:
        logger.debug("ZenShift ensure_key_active: %s", exc)


def _background_loop(interval: float = 10.0):
    while not _stop_event.is_set():
        try:
            _ensure_key_active()
            api = _get_plugin_api()
            if api is not None:
                api.check_timed()
        except Exception:
            pass
        _stop_event.wait(interval)


def _start_background_thread(interval: float = 10.0):
    global _background_thread
    if _background_thread is not None and _background_thread.is_alive():
        return
    _stop_event.clear()
    _background_thread = threading.Thread(
        target=_background_loop, args=(interval,),
        daemon=True, name="zenshift-bg",
    )
    _background_thread.start()
    logger.info("ZenShift: bg thread started (%ss)", interval)


def _on_session_start():
    try:
        api = _get_plugin_api()
        if api is None:
            return
        result = api.reset_session()
        if result.get("status") == "rotated_for_new_session":
            logger.info("ZenShift: session rotate")
    except Exception as exc:
        logger.debug("ZenShift session start: %s", exc)


def install():
    global _integration_installed
    if _integration_installed:
        return
    logger.info("ZenShift integration installing...")
    _ensure_key_active()
    _install_error_feed()
    _install_client_key_injection()
    _start_background_thread(interval=10.0)
    _on_session_start()
    _integration_installed = True
    logger.info("ZenShift integration installed")
    import atexit
    atexit.register(lambda: _stop_event.set())


def rotate_now() -> dict:
    try:
        api = _get_plugin_api()
        if api is None:
            return {"status": "error", "message": "API unavailable"}
        result = api.force_rotate()
        _ensure_key_active()
        current = os.environ.get(_ENV_VAR, "")
        return {
            "status": "ok",
            "new_key": current[:12] + "..." if len(current) > 12 else current,
            "new_key_index": result.get("new_key_index"),
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
