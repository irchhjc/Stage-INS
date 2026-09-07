"""Copie une base DSF existante vers une base vide sans modifier les données source."""

import argparse
import os

from sqlalchemy import create_engine, func, inspect, select, text

from app.extensions import db
import app.models  # noqa: F401 - enregistre les tables dans les métadonnées SQLAlchemy


def _arguments():
    parser = argparse.ArgumentParser(description="Migrer la base DSF vers PostgreSQL.")
    parser.add_argument(
        "--source",
        default=os.environ.get("SOURCE_DATABASE_URL"),
        help="URL SQLAlchemy de la base source (ou SOURCE_DATABASE_URL).",
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("TARGET_DATABASE_URL"),
        help="URL SQLAlchemy de la base cible vide (ou TARGET_DATABASE_URL).",
    )
    return parser.parse_args()


def _assert_source_schema(source_engine):
    existing = set(inspect(source_engine).get_table_names())
    expected = {table.name for table in db.metadata.sorted_tables}
    missing = sorted(expected - existing)
    if missing:
        raise RuntimeError(f"La base source est incomplète. Tables absentes : {', '.join(missing)}")


def _assert_empty_target(connection):
    populated = []
    for table in db.metadata.sorted_tables:
        if connection.execute(select(func.count()).select_from(table)).scalar_one():
            populated.append(table.name)
    if populated:
        raise RuntimeError(
            "Migration annulée : la base cible contient déjà des données dans : "
            + ", ".join(populated)
        )


def _synchronise_postgres_sequences(connection):
    if connection.dialect.name != "postgresql":
        return
    quote = connection.dialect.identifier_preparer.quote
    for table in db.metadata.sorted_tables:
        if "id" not in table.c or not table.c.id.primary_key:
            continue
        sequence_name = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
            {"table_name": table.name},
        ).scalar_one_or_none()
        if not sequence_name:
            continue
        connection.execute(
            text(
                f"SELECT setval(CAST(:sequence_name AS regclass), "
                f"COALESCE(MAX(id), 1), COUNT(*) > 0) FROM {quote(table.name)}"
            ),
            {"sequence_name": sequence_name},
        )


def migrate(source_url, target_url):
    if not source_url or not target_url:
        raise RuntimeError("Les URL source et cible sont obligatoires.")
    if source_url == target_url:
        raise RuntimeError("Les bases source et cible doivent être différentes.")

    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url, pool_pre_ping=True)
    try:
        _assert_source_schema(source_engine)
        db.metadata.create_all(target_engine)
        copied = {}
        with source_engine.connect() as source, target_engine.begin() as target:
            _assert_empty_target(target)
            for table in db.metadata.sorted_tables:
                rows = source.execute(select(table)).mappings()
                count = 0
                batch = []
                for row in rows:
                    batch.append(dict(row))
                    if len(batch) == 1000:
                        target.execute(table.insert(), batch)
                        count += len(batch)
                        batch.clear()
                if batch:
                    target.execute(table.insert(), batch)
                    count += len(batch)
                copied[table.name] = count
            _synchronise_postgres_sequences(target)
        return copied
    finally:
        source_engine.dispose()
        target_engine.dispose()


def main():
    args = _arguments()
    copied = migrate(args.source, args.target)
    print("Migration terminée sans modification de la base source.")
    for table_name, row_count in copied.items():
        print(f"- {table_name}: {row_count} ligne(s)")


if __name__ == "__main__":
    main()
