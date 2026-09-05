from sqlalchemy import inspect, text

from app.extensions import db
from app.models import User
from app.services.auth_service import create_user


def upgrade_legacy_schema():
    """Ajoute les colonnes d'affectation aux bases SQLite créées avant la gestion des comptes."""
    inspector = inspect(db.engine)
    if "dsfs" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("dsfs")}
    statements = []
    if "assigned_to_id" not in existing:
        statements.append("ALTER TABLE dsfs ADD COLUMN assigned_to_id INTEGER REFERENCES users(id)")
    if "assigned_by_id" not in existing:
        statements.append("ALTER TABLE dsfs ADD COLUMN assigned_by_id INTEGER REFERENCES users(id)")
    if "assigned_at" not in existing:
        statements.append("ALTER TABLE dsfs ADD COLUMN assigned_at DATETIME")
    with db.engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_dsfs_assigned_to_id ON dsfs (assigned_to_id)"))


def ensure_initial_admin(username, password):
    existing = User.query.filter_by(username=username).first()
    if existing:
        if existing.role != "admin":
            existing.role = "admin"
            db.session.commit()
        return existing
    return create_user(username, password, role="admin")

