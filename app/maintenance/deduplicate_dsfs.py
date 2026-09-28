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
    deletion_candidate_ids: tuple[int, ...]
    statuses: dict[str, int]
    assigned_count: int
    unassigned_count: int


def analyze_duplicates(dsfs, key_mode="niu-year"):
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
        candidates = [row for row in rows if row.status != "completed"] if completed else []
        status_counts = Counter(row.status for row in rows)
        assigned_count = sum(row.assigned_to_id is not None for row in rows)
        duplicate_groups.append(
            DuplicateGroup(
                key=key,
                ids=tuple(sorted(row.id for row in rows)),
                completed_ids=tuple(sorted(row.id for row in completed)),
                deletion_candidate_ids=tuple(sorted(row.id for row in candidates)),
                statuses=dict(sorted(status_counts.items())),
                assigned_count=assigned_count,
                unassigned_count=len(rows) - assigned_count,
            )
        )

    duplicate_groups.sort(key=lambda group: group.key)
    return duplicate_groups, ignored


def build_report(dsfs, key_mode="niu-year", detail_limit=20):
    rows = list(dsfs)
    groups, ignored = analyze_duplicates(rows, key_mode)
    groups_with_completed = [group for group in groups if group.completed_ids]
    protected_groups = [group for group in groups if not group.completed_ids]
    candidate_ids = [
        dsf_id
        for group in groups_with_completed
        for dsf_id in group.deletion_candidate_ids
    ]
    assigned_candidates = {
        row.id for row in rows if row.id in set(candidate_ids) and row.assigned_to_id is not None
    }
    status_counts = Counter(
        row.status for row in rows if row.id in set(candidate_ids)
    )

    return {
        "key_mode": key_mode,
        "total_dsfs": len(rows),
        "rows_ignored_for_incomplete_key": ignored,
        "duplicate_groups": len(groups),
        "duplicate_rows": sum(len(group.ids) for group in groups),
        "groups_with_completed_dsf": len(groups_with_completed),
        "groups_without_completed_dsf_protected": len(protected_groups),
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
            "Repère les DSF en double et supprime uniquement les versions non terminées "
            "lorsqu'au moins une version terminée existe dans le groupe."
        )
    )
    parser.add_argument("--key", choices=KEY_MODES, default="niu-year")
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
        report = build_report(dsfs, key_mode=args.key, detail_limit=max(0, args.limit))

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
