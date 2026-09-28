import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import DSF


CONFIRMATION_TOKEN = "DELETE_NON_COMPLETED_DUPLICATES"
KEY_MODES = ("niu-year", "numero-dsf", "niu-year-numero")
POLICIES = ("completed-only", "keep-best")


def _normalize(value):
    return " ".join(str(value or "").split()).casefold()


def duplicate_key(dsf, key_mode):
    niu = _normalize(dsf.niu)
    year = _normalize(dsf.annee)
    numero = _normalize(dsf.numero_dsf)

    if key_mode == "niu-year":
        return (niu, year) if niu and year else None
    if key_mode == "numero-dsf":
        return (numero,) if numero else None
    if key_mode == "niu-year-numero":
        return (niu, year, numero) if niu and year and numero else None
    raise ValueError(f"Mode de clé inconnu : {key_mode}")


@dataclass(frozen=True)
class DuplicateGroup:
    key: tuple[str, ...]
    ids: tuple[int, ...]
    completed_ids: tuple[int, ...]
    kept_ids: tuple[int, ...]
    deletion_candidate_ids: tuple[int, ...]
    statuses: dict[str, int]
    assigned_count: int
    unassigned_count: int


def _survivor_rank(dsf):
    status_priority = {"completed": 3, "in_progress": 2, "not_started": 1}
    return (
        status_priority.get(dsf.status, 0),
        dsf.assigned_to_id is not None,
        float(dsf.progress or 0),
        -dsf.id,
    )


def analyze_duplicates(dsfs, key_mode="niu-year", policy="completed-only"):
    if policy not in POLICIES:
        raise ValueError(f"Politique inconnue : {policy}")
    grouped = defaultdict(list)
    ignored = 0
    for dsf in dsfs:
        key = duplicate_key(dsf, key_mode)
        if key is None:
            ignored += 1
            continue
        grouped[key].append(dsf)

    duplicate_groups = []
    for key, rows in grouped.items():
        if len(rows) < 2:
            continue
        completed = [row for row in rows if row.status == "completed"]
        if completed:
            kept = completed
            candidates = [row for row in rows if row.status != "completed"]
        elif policy == "keep-best":
            survivor = max(rows, key=_survivor_rank)
            kept = [survivor]
            candidates = [row for row in rows if row.id != survivor.id]
        else:
            kept = rows
            candidates = []
        status_counts = Counter(row.status for row in rows)
        assigned_count = sum(row.assigned_to_id is not None for row in rows)
        duplicate_groups.append(
            DuplicateGroup(
                key=key,
                ids=tuple(sorted(row.id for row in rows)),
                completed_ids=tuple(sorted(row.id for row in completed)),
                kept_ids=tuple(sorted(row.id for row in kept)),
                deletion_candidate_ids=tuple(sorted(row.id for row in candidates)),
                statuses=dict(sorted(status_counts.items())),
                assigned_count=assigned_count,
                unassigned_count=len(rows) - assigned_count,
            )
        )

    duplicate_groups.sort(key=lambda group: group.key)
    return duplicate_groups, ignored


def build_report(dsfs, key_mode="niu-year", policy="completed-only", detail_limit=20):
    rows = list(dsfs)
    groups, ignored = analyze_duplicates(rows, key_mode, policy)
    groups_with_completed = [group for group in groups if group.completed_ids]
    groups_without_completed = [group for group in groups if not group.completed_ids]
    candidate_ids = [
        dsf_id
        for group in groups
        for dsf_id in group.deletion_candidate_ids
    ]
    candidate_id_set = set(candidate_ids)
    assigned_candidates = {
        row.id for row in rows if row.id in candidate_id_set and row.assigned_to_id is not None
    }
    status_counts = Counter(
        row.status for row in rows if row.id in candidate_id_set
    )

    return {
        "key_mode": key_mode,
        "policy": policy,
        "total_dsfs": len(rows),
        "rows_ignored_for_incomplete_key": ignored,
        "duplicate_groups": len(groups),
        "duplicate_rows": sum(len(group.ids) for group in groups),
        "groups_with_completed_dsf": len(groups_with_completed),
        "groups_without_completed_dsf": len(groups_without_completed),
        "groups_without_completed_dsf_protected": (
            len(groups_without_completed) if policy == "completed-only" else 0
        ),
        "deletion_candidates": len(candidate_ids),
        "assigned_deletion_candidates": len(assigned_candidates),
        "unassigned_deletion_candidates": len(candidate_ids) - len(assigned_candidates),
        "candidate_statuses": dict(sorted(status_counts.items())),
        "candidate_ids": candidate_ids,
        "details": [asdict(group) for group in groups[:detail_limit]],
        "details_truncated": max(0, len(groups) - detail_limit),
    }


def _arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Repère les DSF en double et prépare une déduplication déterministe qui ne supprime "
            "jamais une DSF terminée."
        )
    )
    parser.add_argument("--key", choices=KEY_MODES, default="niu-year")
    parser.add_argument(
        "--policy",
        choices=POLICIES,
        default="completed-only",
        help=(
            "completed-only protège les groupes sans DSF terminée ; keep-best conserve une seule "
            "DSF dans ces groupes, par priorité de statut, affectation, progression puis ancienneté."
        ),
    )
    parser.add_argument("--limit", type=int, default=20, help="Nombre maximal de groupes détaillés.")
    parser.add_argument("--json", action="store_true", help="Produit un rapport JSON.")
    parser.add_argument("--apply", action="store_true", help="Applique la suppression transactionnelle.")
    parser.add_argument(
        "--confirm",
        help=f"Jeton obligatoire avec --apply : {CONFIRMATION_TOKEN}",
    )
    return parser.parse_args()


def _write_manifest(app, report):
    manifest_dir = Path(app.instance_path) / "maintenance"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = manifest_dir / f"dsf_deduplication_{timestamp}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def main():
    args = _arguments()
    if args.apply and args.confirm != CONFIRMATION_TOKEN:
        raise SystemExit(
            f"Suppression refusée : utilisez --confirm {CONFIRMATION_TOKEN} après validation de l'aperçu."
        )

    app = create_app()
    with app.app_context():
        dsfs = DSF.query.order_by(DSF.id).all()
        report = build_report(
            dsfs,
            key_mode=args.key,
            policy=args.policy,
            detail_limit=max(0, args.limit),
        )

        if not args.apply:
            report["mode"] = "preview"
            print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report)
            return

        report["mode"] = "apply"
        report["applied_at"] = datetime.now(timezone.utc).isoformat()
        manifest = _write_manifest(app, report)
        candidate_ids = report["candidate_ids"]
        try:
            if candidate_ids:
                DSF.query.filter(DSF.id.in_(candidate_ids)).delete(synchronize_session=False)
            db.session.commit()
        except Exception:
            db.session.rollback()
            manifest.unlink(missing_ok=True)
            raise

        report["deleted"] = len(candidate_ids)
        report["manifest"] = str(manifest)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report)


if __name__ == "__main__":
    main()
