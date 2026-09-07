from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select

from app.extensions import db
from app.models import User
from scripts.migrate_database import migrate
from config import normalize_database_url


def test_render_postgres_url_uses_psycopg3_driver():
    assert normalize_database_url("postgresql://user:secret@host/db") == (
        "postgresql+psycopg://user:secret@host/db"
    )
    assert normalize_database_url("postgres://user:secret@host/db") == (
        "postgresql+psycopg://user:secret@host/db"
    )


def test_migration_copies_rows_and_refuses_a_populated_target(tmp_path):
    source_url = f"sqlite:///{(tmp_path / 'source.db').as_posix()}"
    target_url = f"sqlite:///{(tmp_path / 'target.db').as_posix()}"
    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)
    try:
        db.metadata.create_all(source_engine)
        with source_engine.begin() as connection:
            connection.execute(
                User.__table__.insert(),
                {
                    "id": 7,
                    "username": "controleur",
                    "password_hash": "hash-test",
                    "role": "controller",
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc),
                },
            )

        copied = migrate(source_url, target_url)
        assert copied["users"] == 1
        with target_engine.connect() as connection:
            assert connection.execute(select(func.count()).select_from(User.__table__)).scalar_one() == 1

        with pytest.raises(RuntimeError, match="contient déjà des données"):
            migrate(source_url, target_url)
    finally:
        source_engine.dispose()
        target_engine.dispose()
