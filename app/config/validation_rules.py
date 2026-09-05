"""Paramètres des contrôles automatiques. Les règles ne modifient jamais une valeur."""

BALANCE_RULE = {
    "code": "BALANCE_ACTIF_PASSIF",
    "actif": "TOTAL GENERAL (NET_N)",
    "passif": "TOTAL GENERAL PASSIF(N)",
    "tolerance": 0.5,
}

NET_RULE_SUFFIXES = {
    "brut": " (BRUT)",
    "depreciation": " (AMORT/DEPREC)",
    "net": " (NET_N)",
    "tolerance": 0.5,
}

