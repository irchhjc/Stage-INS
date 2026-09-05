"""Mapping de structure DSF.

Les libellés ci-dessous servent uniquement à repérer les limites des fiches.
Ils ne remplacent ni ne normalisent jamais les en-têtes du classeur.
"""

FICHE_DEFINITIONS = [
    {"code": "IDENT", "name": "Identification", "start": None},
    {"code": "BILAN_ACTIF", "name": "Bilan Actif", "start": "IMMOBILISATIONS INCORPORELLES (BRUT)"},
    {"code": "BILAN_PASSIF", "name": "Bilan Passif", "start": "Capital NET (N)"},
    {"code": "COMPTE_RESULTAT", "name": "Compte de résultat", "start": "TA Ventes de marchandises(N)"},
    {"code": "NOTE_3A", "name": "Note 3A — Immobilisations brutes", "start": "La note 3A est-elle renseigner ?"},
    {"code": "NOTE_AMORT", "name": "Note amortissements / dépréciations", "start": "La note 3D est-elle renseigner ?"},
    {"code": "NOTE_4", "name": "Note 4 — Immobilisations financières", "start": "La note 4 est-elle renseignée ?"},
    {"code": "NOTE_5_ACTIF", "name": "Note 5 — Actif circulant HAO", "start": "La note 5 (Actif circulant HAO)  est-elle renseignée ?"},
    {"code": "NOTE_5_PASSIF", "name": "Note 5 — Dettes circulantes HAO", "start": "La note 5 (Dettes circulantes HAO)  est-elle renseignée ?"},
    {"code": "NOTE_6", "name": "Note 6 — Stocks", "start": "La note 6 est-elle renseignée ?"},
    {"code": "NOTE_7", "name": "Note 7 — Clients", "start": "La note 7 est-elle renseignée ?"},
    {"code": "NOTE_8", "name": "Note 8 — Autres créances", "start": "La note 8 est-elle renseignée ?"},
    {"code": "NOTE_9", "name": "Note 9 — Titres de placement", "start": "La note 9 est-elle renseignée ?"},
    {"code": "NOTE_10", "name": "Note 10 — Valeurs à encaisser", "start": "La note 10 est-elle renseignée ?"},
    {"code": "NOTE_11", "name": "Note 11 — Disponibilités", "start": "La note 11 est-elle renseignée ?"},
    {"code": "NOTE_14", "name": "Note 14 — Primes et réserves", "start": "La note 14 est-elle renseignée ?"},
    {"code": "NOTE_15A", "name": "Note 15A — Subventions et provisions réglementées", "start": "La note 15A est-elle renseignée ?"},
    {"code": "NOTE_15B", "name": "Note 15B — Autres fonds propres", "start": "La note 15B est-elle renseignée ?"},
    {"code": "NOTE_16A", "name": "Note 16A — Dettes financières et provisions", "start": "La note 16A est-elle renseignée ?"},
    {"code": "NOTE_16B", "name": "Note 16B — Engagements de retraite", "start": "La note 16B est-elle renseignée ?"},
    {"code": "NOTE_17", "name": "Note 17 — Fournisseurs", "start": "La note 17 est-elle renseignée ?"},
    {"code": "NOTE_18", "name": "Note 18 — Dettes fiscales et sociales", "start": "La note 18 est-elle renseignée ?"},
    {"code": "NOTE_19", "name": "Note 19 — Autres dettes", "start": "La note 19 est-elle renseignée ?"},
    {"code": "NOTE_20", "name": "Note 20 — Banques et crédits de trésorerie", "start": "La note 20 est-elle renseignée ?"},
    {"code": "NOTE_21", "name": "Note 21 — Ventes", "start": "La note 21 est-elle renseignée ?"},
    {"code": "NOTE_22", "name": "Note 22 — Achats", "start": "La note 22 est-elle renseignée ?"},
    {"code": "NOTE_23", "name": "Note 23 — Transports", "start": "La note 23 est-elle renseignée ?"},
    {"code": "NOTE_24", "name": "Note 24 — Services extérieurs", "start": "La note 24 est-elle renseignée ?"},
    {"code": "NOTE_25", "name": "Note 25 — Impôts et taxes", "start": "La note 25 est-elle renseignée ?"},
    {"code": "NOTE_26", "name": "Note 26 — Autres charges", "start": "La note 26 est-elle renseignée ?"},
    {"code": "NOTE_27A", "name": "Note 27A — Charges de personnel", "start": "La note 27A est-elle renseignée ?"},
    {"code": "NOTE_27B", "name": "Note 27B — Effectifs et masse salariale", "start": "La note 27B est-elle renseignée ?"},
    {"code": "NOTE_29", "name": "Note 29 — Résultat financier", "start": "La note 29 est-elle renseignée ?"},
    {"code": "NOTE_34", "name": "Note 34 — Analyse financière", "start": "La note 34 est-elle renseignée ?"},
    {"code": "TRACE", "name": "Traçabilité de saisie", "start": "Nom et Prénoms de l'opérateur"},
]

FICHE_BY_CODE = {item["code"]: item for item in FICHE_DEFINITIONS}


# Libellés d'affichage uniquement. Les clés originales restent stockées sans changement.
MEASURE_LABELS = {
    "BRUT": "BRUT",
    "AMORT/DEPREC": "AMORT./DÉPRÉC.",
    "NET_N": "NET N",
    "NET_N-1": "NET N-1",
    "NET_N_1": "NET N-1",
    "N": "N",
    "N-1": "N-1",
    "EFFECTIF_HOMME": "Hommes",
    "EFFECTIF_FEMME": "Femmes",
    "EFFECTIF_TOTAL": "Total",
    "MASSE_SALARIALE_HOMME": "Hommes",
    "MASSE_SALARIALE_FEMME": "Femmes",
    "MASSE_SALARIALE_TOTAL": "Total",
}

