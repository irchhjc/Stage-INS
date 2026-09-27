import argparse
from pathlib import Path, PureWindowsPath

from app import create_app
from app.extensions import db
from app.models import ImportSession


def _arguments():
    parser = argparse.ArgumentParser(
        description="Relie les imports restaurés aux fichiers du volume instance/uploads."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Enregistre les nouveaux chemins. Sans cette option, affiche seulement l'aperçu.",
    )
    return parser.parse_args()


def _source_folder_name(filepath):
    if "\\" in filepath:
        return PureWindowsPath(filepath).parent.name
    return Path(filepath).parent.name


def main():
    args = _arguments()
    app = create_app()
    with app.app_context():
        upload_root = Path(app.config["UPLOAD_FOLDER"]).resolve()
        updates = []
        missing = []
        for import_session in ImportSession.query.order_by(ImportSession.id):
            current_path = Path(import_session.filepath)
            if current_path.exists():
                continue
            candidate = upload_root / _source_folder_name(import_session.filepath) / "original.xlsx"
            if candidate.exists():
                updates.append((import_session, candidate.resolve()))
            else:
                missing.append((import_session.id, import_session.filename))

        print(f"Chemins à mettre à jour : {len(updates)}")
        print(f"Fichiers introuvables : {len(missing)}")
        for session_id, filename in missing[:20]:
            print(f"- import {session_id}: {filename}")
        if missing:
            raise SystemExit(
                "Reliaison annulée : copiez d'abord tous les dossiers instance/uploads du serveur source."
            )
        if not args.apply:
            print("Aperçu seulement. Relancez avec --apply pour enregistrer les chemins.")
            return
        for import_session, candidate in updates:
            import_session.filepath = str(candidate)
        db.session.commit()
        print(f"Reliaison terminée : {len(updates)} chemin(s) mis à jour.")


if __name__ == "__main__":
    main()
