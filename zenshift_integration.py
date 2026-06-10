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
_ENV_PATH = Path(os.path.expanduser("~/.hermes/.env"))
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

def _write_env_file(env: dict[str, str]) -> None:
    try:
        content = "\n".join(f"{k}={v}" for k, v in env.items() if k.strip())
        tmp = _ENV_PATH.with_suffix(".env.tmp")
        tmp.write_text(content + "\n")
        tmp.replace(_ENV_PATH)
    except OSError as exc:
        logger.warning("Failed to write %s: %s", _ENV_PATH, exc)

def _get_plugin_api():
    try:
        from zenshift.dashboard import plugin_api
        return plugin_api
    except ImportError:
        try:
            import importlib
            spec = importlib.util.find_spec("zenshift.dashboard.plugin_api")
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
        except (ImportError, AttributeError):
            pass
        return None

def _install_error_feed():
    global _ORIGINAL_CLASSIFY_API_ERROR
    try:
        from agent import error_classifier
    except ImportError:
        logger.warning("Cannot import agent.error_classifier")
        return
    if not hasattr(error_classifier, "classify_api_error"):
        return

    _ORIGINAL_CLASSIFY_API_ERROR = error_classifier.classify_api_error

    def _patched_classify_api_error(error, **kwargs):
        provider = kwargs.get("provider", "").strip().lower()
        if "opencode" in provider or provider in ("zen",):
            try:
                error_text = str(error)
                api = _get_plugin_api()
                if api is not None:
                    result = api.report_error({"error": error_text})
                    action = result.get("action", "none")
                    if action == "ratelimit_rotated":
                        logger.info("ZenShift: rotated on rate-limit")
                    elif action == "blacklisted_and_rotated":
                        logger.info("ZenShift: blacklisted + rotated on dead key")
            except Exception:
                pass
        return _ORIGINAL_CLASSIFY_API_ERROR(error, **kwargs)

    error_classifier.classify_api_error = _patched_classify_api_error
    logger.info("ZenShift: patched classify_api_error")

def _install_client_key_injection():
    try:
        import run_agent
    except ImportError:
        logger.warning("Cannot import run_agent")
        return
    cls = getattr(run_agent, "AIAgent", None)
    if cls is None:
        return
    orig = getattr(cls, "_create_request_openai_client", None)
    if orig is None:
        return

    def _patched_create_client(self, **kwargs):
        _ensure_key_active()
        # Count API call attempt (for per-api-call strategy)
        try:
            api = _get_plugin_api()
            if api is not None:
                api.report_tool_call({})
        except Exception:
            pass
        return orig(self, **kwargs)

    setattr(cls, "_create_request_openai_client", _patched_create_client)
    logger.info("ZenShift: patched _create_request_openai_client")

def _ensure_key_active():
    try:
        api = _get_plugin_api()
        if api is None:
            return
        api.check_timed()
        if api._active_key and os.environ.get(_ENV_VAR) != api._active_key:
            os.environ[_ENV_VAR] = api._active_key
            env = _read_env_file()
            env[_ENV_VAR] = api._active_key
            _write_env_file(env)
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
        if result.get("rotated"):
            key = result.get("new_key", "")
            logger.info("ZenShift: session rotate -> %s...", key[:8] if key else "none")
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

