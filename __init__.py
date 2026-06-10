"""ZenShift — OpenCode Zen API key rotation manager for Hermes Agent."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx):
    """Register the ZenShift plugin.

    Two responsibilities:
      1. Dashboard backend (FastAPI APIRouter) — auto-mounted by the
         Hermes dashboard via dashboard/manifest.json at startup.
      2. Agent integration hooks — feed API errors back for auto-rotation,
         patch os.environ, run background timed-rotation thread.

    Integration is best-effort; the dashboard UI works independently.
    """
    logger.info("ZenShift v0.1.0 — dashboard UI at /zenshift")

    # Automatic integration (best-effort — may fail if Hermes agent
    # internals are not importable in this process, e.g. dashboard-only).
    try:
        from zenshift.zenshift_integration import install as _install_integration
        _install_integration()
        logger.info("ZenShift auto-integration installed")
    except ImportError:
        logger.info(
            "ZenShift auto-integration skipped (agent modules not available)"
        )
    except Exception as exc:
        logger.warning("ZenShift auto-integration failed: %s", exc)

    return None
