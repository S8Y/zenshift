"""ZenShift plugin — OpenCode Zen API key rotation manager."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx):
    """Register the ZenShift plugin.

    Two responsibilities:
      1. The ZenShift dashboard backend is auto-mounted by the Hermes dashboard
         runtime via dashboard/manifest.json (FastAPI APIRouter).
      2. Install automatic integration hooks that feed API errors back into
         ZenShift for auto-rotation: patches os.environ, hooks the agent'''s
         error classifier, and runs a background timed-rotation thread.

    All integration patches are in zenshift.zenshift_integration.install().
    """
    # Dashboard UI registration
    logger.info("ZenShift plugin loaded -- dashboard UI available at /zenshift")

    # Automatic integration (best-effort)
    try:
        from zenshift.zenshift_integration import install as _install_integration
        _install_integration()
        logger.info("ZenShift auto-integration installed")
    except ImportError as exc:
        logger.info(
            "ZenShift auto-integration skipped (agent modules not available): %s",
            exc,
        )
    except Exception as exc:
        logger.warning("ZenShift auto-integration failed: %s", exc)

    return None

