"""Bootstrap a new Vela deployment: validate env, create DB tables, seed data."""
from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

REQUIRED_ENV = ["DATABASE_URL", "REDIS_URL", "JWT_SECRET"]
OPTIONAL_ENV = ["CAISO_NODE", "ERCOT_API_KEY", "SLACK_WEBHOOK_URL", "VELA_ENV"]


def check_environment() -> bool:
    """Verify required environment variables are set."""
    logger.info("Checking environment variables...")
    ok = True
    for var in REQUIRED_ENV:
        val = os.getenv(var, "")
        if val:
            masked = val[:4] + "****" if len(val) > 4 else "****"
            logger.info("  [OK] %s = %s", var, masked)
        else:
            logger.warning("  [MISSING] %s", var)
            ok = False
    for var in OPTIONAL_ENV:
        val = os.getenv(var, "")
        if val:
            logger.info("  [OK] %s (optional)", var)
        else:
            logger.info("  [skipped] %s (optional)", var)
    return ok


def check_imports() -> bool:
    """Verify critical packages are installed."""
    logger.info("Checking package imports...")
    packages = ["fastapi", "uvicorn", "pydantic", "numpy", "celery"]
    ok = True
    for pkg in packages:
        try:
            __import__(pkg)
            logger.info("  [OK] %s", pkg)
        except ImportError:
            logger.error("  [MISSING] %s", pkg)
            ok = False
    return ok


def create_directories() -> None:
    """Create required runtime directories."""
    dirs = ["logs", "data/raw", "data/processed", "models"]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        logger.info("  [created] %s/", d)


def bootstrap() -> None:
    logger.info("Vela Bootstrap Starting...")
    logger.info("Environment: %s", os.getenv("VELA_ENV", "development"))

    env_ok = check_environment()
    pkg_ok = check_imports()

    logger.info("Creating runtime directories...")
    create_directories()

    if env_ok and pkg_ok:
        logger.info("Bootstrap complete. Run 'make run-api' to start the server.")
    else:
        logger.warning("Bootstrap completed with warnings. Some features may be unavailable.")
        logger.warning("Run 'pip install -e .[dev]' and set required env vars.")

    # Optionally seed data
    if os.getenv("SEED_DATA", "false").lower() == "true":
        logger.info("Seeding sample data...")
        from scripts.seed_data import seed_all
        seed_all()


if __name__ == "__main__":
    bootstrap()
