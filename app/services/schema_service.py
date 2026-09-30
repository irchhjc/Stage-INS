"""Identification des schémas DSF connus sans modifier les en-têtes source."""

import hashlib

from app.services.mapping_service import normalize_label


FULL_DSF_SCHEMA_CODE = "DSF_1777_2026"
FULL_DSF_SCHEMA_LABEL = "Schéma DSF complet - 1 777 colonnes"
FULL_DSF_COLUMN_COUNT = 1777
FULL_DSF_SCHEMA_FINGERPRINT = "e08c5eac7e1c96a78e65fd1bcf8cc07a067f62f7db90f88239a88bc1d56fd1a6"


def schema_fingerprint(headers):
    """Empreinte ordonnée et tolérante aux accents/espaces pour la détection."""
    normalized = "\x1f".join(normalize_label(header) for header in headers)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def identify_schema(headers):
    column_count = len(headers)
    fingerprint = schema_fingerprint(headers)
    recognized = (
        column_count == FULL_DSF_COLUMN_COUNT
        and fingerprint == FULL_DSF_SCHEMA_FINGERPRINT
    )
    return {
        "code": FULL_DSF_SCHEMA_CODE if recognized else None,
        "label": FULL_DSF_SCHEMA_LABEL if recognized else "Schéma DSF personnalisé",
        "recognized": recognized,
        "column_count": column_count,
        "fingerprint": fingerprint,
    }
