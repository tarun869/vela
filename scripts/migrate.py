"""Run Alembic database migrations."""
from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def run_migrations(command: str = "upgrade", revision: str = "head") -> int:
    """Run an Alembic migration command."""
    alembic_cmd = ["alembic", command, revision]
    logger.info("Running: %s", " ".join(alembic_cmd))
    result = subprocess.run(alembic_cmd, capture_output=True, text=True)
    if result.stdout:
        logger.info(result.stdout)
    if result.stderr:
        logger.error(result.stderr)
    return result.returncode


def current_revision() -> str:
    """Return the current migration revision."""
    result = subprocess.run(["alembic", "current"], capture_output=True, text=True)
    return result.stdout.strip()


def generate_migration(message: str) -> int:
    """Auto-generate a new migration from model changes."""
    cmd = ["alembic", "revision", "--autogenerate", "-m", message]
    logger.info("Generating migration: %s", message)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        logger.info(result.stdout)
    return result.returncode


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Vela Database Migration Tool")
    parser.add_argument("command", choices=["upgrade", "downgrade", "current", "history", "generate"])
    parser.add_argument("--revision", default="head")
    parser.add_argument("--message", default="auto-migration")
    args = parser.parse_args()

    if args.command == "current":
        print(current_revision())
    elif args.command == "generate":
        sys.exit(generate_migration(args.message))
    else:
        sys.exit(run_migrations(args.command, args.revision))
