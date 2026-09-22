"""Bounded reconnection for the initial authentication read only."""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError
from app.extensions import db


def read_user_with_reconnect(model, user_id):
    try:
        return db.session.get(model, user_id)
    except (OperationalError, InterfaceError) as error:
        # This runs before the route: no business write has happened yet.
        # A Windows permission failure or saturation must not be retried here.
        if not error.connection_invalidated or "10013" in str(error.orig):
            raise
        db.session.remove()
        return db.session.get(model, user_id)


def failure_code(error):
    if "10013" in str(getattr(error, "orig", "")):
        return "database_access_denied"
    if isinstance(error, TimeoutError):
        return "database_pool_busy"
    if getattr(getattr(error, "orig", None), "sqlstate", None) == "53300":
        return "database_connection_limit"
    return "database_unavailable"


def configure_connection_logging(app):
    if app.testing:
        app.extensions["connection_logger"] = app.logger
        return
    folder = Path(app.instance_path) / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    # Separate files avoid rotation conflicts if several workers run.
    logger = logging.getLogger(f"dsf.connections.{os.getpid()}")
    filename = str(folder / f"database-{os.getpid()}.log")
    if not any(getattr(h, "baseFilename", None) == filename for h in logger.handlers):
        handler = RotatingFileHandler(filename, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    app.extensions["connection_logger"] = logger
