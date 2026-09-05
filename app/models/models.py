from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="controller", index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_login_at = db.Column(db.DateTime(timezone=True))

    assigned_dsfs = db.relationship(
        "DSF",
        foreign_keys="DSF.assigned_to_id",
        back_populates="assignee",
    )
    assignments_made = db.relationship(
        "DSF",
        foreign_keys="DSF.assigned_by_id",
        back_populates="assigned_by",
    )

    @property
    def is_admin(self):
        return self.role == "admin"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class ImportSession(db.Model):
    __tablename__ = "import_sessions"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.Text, nullable=False)
    sheet_name = db.Column(db.String(255), nullable=False)
    header_row = db.Column(db.Integer, nullable=False, default=1)
    row_count = db.Column(db.Integer, nullable=False, default=0)
    column_count = db.Column(db.Integer, nullable=False, default=0)
    imported_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    dsfs = db.relationship("DSF", backref="import_session", cascade="all, delete-orphan")
    columns = db.relationship(
        "ImportColumn",
        backref="import_session",
        cascade="all, delete-orphan",
        order_by="ImportColumn.column_index",
    )


class ImportColumn(db.Model):
    __tablename__ = "import_columns"
    __table_args__ = (
        db.UniqueConstraint("import_session_id", "column_index", name="uq_import_column_position"),
    )

    id = db.Column(db.Integer, primary_key=True)
    import_session_id = db.Column(
        db.Integer, db.ForeignKey("import_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    column_index = db.Column(db.Integer, nullable=False)
    excel_column_letter = db.Column(db.String(12), nullable=False)
    variable_name = db.Column(db.Text, nullable=False)
    fiche_code = db.Column(db.String(32), nullable=False, index=True)
    fiche_name = db.Column(db.String(160), nullable=False)


class DSF(db.Model):
    __tablename__ = "dsfs"
    __table_args__ = (
        db.UniqueConstraint("import_session_id", "row_index", name="uq_import_dsf_row"),
    )

    id = db.Column(db.Integer, primary_key=True)
    import_session_id = db.Column(
        db.Integer, db.ForeignKey("import_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_index = db.Column(db.Integer, nullable=False)
    numero_dsf = db.Column(db.Text)
    numero_dsf_t = db.Column(db.Text)
    niu = db.Column(db.Text, index=True)
    cle = db.Column(db.Text)
    raison_sociale = db.Column(db.Text, index=True)
    sigle = db.Column(db.Text, index=True)
    annee = db.Column(db.Text, index=True)
    status = db.Column(db.String(24), nullable=False, default="not_started", index=True)
    progress = db.Column(db.Float, nullable=False, default=0.0)
    anomaly_count = db.Column(db.Integer, nullable=False, default=0)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    assigned_at = db.Column(db.DateTime(timezone=True))

    values = db.relationship("DSFValue", backref="dsf", cascade="all, delete-orphan")
    fiche_statuses = db.relationship(
        "FicheStatus", backref="dsf", cascade="all, delete-orphan", order_by="FicheStatus.position"
    )
    audit_logs = db.relationship("AuditLog", backref="dsf", cascade="all, delete-orphan")
    assignee = db.relationship("User", foreign_keys=[assigned_to_id], back_populates="assigned_dsfs")
    assigned_by = db.relationship("User", foreign_keys=[assigned_by_id], back_populates="assignments_made")

    @property
    def progress_percent(self):
        return int(round(self.progress * 100))


class DSFValue(db.Model):
    __tablename__ = "dsf_values"
    __table_args__ = (
        db.UniqueConstraint("dsf_id", "import_column_id", name="uq_dsf_column_value"),
    )

    id = db.Column(db.Integer, primary_key=True)
    dsf_id = db.Column(db.Integer, db.ForeignKey("dsfs.id", ondelete="CASCADE"), nullable=False, index=True)
    import_column_id = db.Column(
        db.Integer, db.ForeignKey("import_columns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variable_name = db.Column(db.Text, nullable=False)
    original_value = db.Column(db.Text, nullable=False)
    current_value = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="unverified", index=True)
    verified = db.Column(db.Boolean, nullable=False, default=False)
    corrected = db.Column(db.Boolean, nullable=False, default=False)
    verification_source = db.Column(db.String(32))
    operator = db.Column(db.String(120))
    verified_at = db.Column(db.DateTime(timezone=True))
    corrected_at = db.Column(db.DateTime(timezone=True))
    comment = db.Column(db.Text)

    column = db.relationship("ImportColumn")


class FicheStatus(db.Model):
    __tablename__ = "fiche_statuses"
    __table_args__ = (
        db.UniqueConstraint("dsf_id", "fiche_code", name="uq_dsf_fiche"),
    )

    id = db.Column(db.Integer, primary_key=True)
    dsf_id = db.Column(db.Integer, db.ForeignKey("dsfs.id", ondelete="CASCADE"), nullable=False, index=True)
    fiche_code = db.Column(db.String(32), nullable=False)
    fiche_name = db.Column(db.String(160), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="not_started", index=True)
    validated_at = db.Column(db.DateTime(timezone=True))
    operator = db.Column(db.String(120))


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    dsf_id = db.Column(db.Integer, db.ForeignKey("dsfs.id", ondelete="CASCADE"), nullable=False, index=True)
    fiche_code = db.Column(db.String(32), index=True)
    variable_name = db.Column(db.Text)
    column_index = db.Column(db.Integer)
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    action = db.Column(db.String(48), nullable=False, index=True)
    operator = db.Column(db.String(120))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
