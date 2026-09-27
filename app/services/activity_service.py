"""Activity groups from original column positions, including duplicate headers."""
import json
import re
import unicodedata
from collections import defaultdict

from app.extensions import db
from app.models import DSF, DSFValue, ImportColumn
from app.services.value_codec import deserialize_value


def is_sub_branch(header):
    normalized = unicodedata.normalize("NFKD", header or "")
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = re.sub(r"[^a-z0-9]", "", normalized.casefold())
    return normalized in {
        "sousbranche", "sousbranchedactivite", "sousbrancheactivite",
        "codesousbranche", "codesousbranchedactivite", "codesousbrancheactivite",
    }


def activity_groups(session_id=None, assigned_only=False):
    columns = ImportColumn.query
    if session_id is not None:
        columns = columns.filter_by(import_session_id=session_id)
    column_ids = [c.id for c in columns.all() if is_sub_branch(c.variable_name)]
    dsfs = db.session.query(DSF.id, DSF.assigned_to_id)
    if session_id is not None:
        dsfs = dsfs.filter(DSF.import_session_id == session_id)
    if assigned_only:
        dsfs = dsfs.filter(DSF.assigned_to_id.is_not(None))
    owners = dict(dsfs.all())
    parts = defaultdict(list)
    if column_ids and owners:
        values = (db.session.query(DSFValue.dsf_id, DSFValue.current_value)
                  .join(ImportColumn).filter(ImportColumn.id.in_(column_ids))
                  .order_by(ImportColumn.column_index))
        for dsf_id, serialized in values:
            if dsf_id in owners:
                raw = deserialize_value(serialized)
                text = str(raw).strip() if raw is not None else ""
                if text and text not in parts[dsf_id]:
                    parts[dsf_id].append(text)
    groups = {}
    by_dsf = {}
    for dsf_id, owner in owners.items():
        key = json.dumps(parts[dsf_id], ensure_ascii=False, separators=(",", ":"))
        label = " — ".join(parts[dsf_id]) or "Sous-branche non renseignée"
        by_dsf[dsf_id] = {"key": key, "label": label}
        group = groups.setdefault(key, {"key": key, "label": label, "ids": [], "free": 0})
        group["ids"].append(dsf_id)
        group["free"] += owner is None
    return by_dsf, sorted(groups.values(), key=lambda g: g["label"].casefold())
