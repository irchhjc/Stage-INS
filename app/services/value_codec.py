import json
import math
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation


TEXT_IDENTIFIERS = {
    "NUMERO DE LA DSF",
    "NUMERO DSF_T",
    "NIU",
    "Cle",
    "Raison sociale",
    "Sigle usuel",
    "Adresse",
    "Ville",
    "Numero de téléphone",
    "Numéro de Téléphone 2",
    "e-mail",
}


def serialize_value(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        payload = {"type": "blank", "value": None}
    elif isinstance(value, bool):
        payload = {"type": "bool", "value": value}
    elif isinstance(value, int):
        payload = {"type": "int", "value": value}
    elif isinstance(value, float):
        payload = {"type": "float", "value": value}
    elif isinstance(value, datetime):
        payload = {"type": "datetime", "value": value.isoformat()}
    elif isinstance(value, date):
        payload = {"type": "date", "value": value.isoformat()}
    elif isinstance(value, time):
        payload = {"type": "time", "value": value.isoformat()}
    elif isinstance(value, str) and value.startswith("="):
        payload = {"type": "formula", "value": value}
    else:
        payload = {"type": "string", "value": str(value)}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def deserialize_value(serialized):
    payload = json.loads(serialized)
    value_type = payload["type"]
    value = payload.get("value")
    if value_type == "blank":
        return None
    if value_type == "datetime":
        return datetime.fromisoformat(value)
    if value_type == "date":
        return date.fromisoformat(value)
    if value_type == "time":
        return time.fromisoformat(value)
    return value


def value_type(serialized):
    return json.loads(serialized)["type"]


def display_value(serialized):
    value = deserialize_value(serialized)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}".replace(",", " ")
        return f"{value:,.6f}".rstrip("0").rstrip(".").replace(",", " ")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return str(value)


def raw_input_value(serialized):
    value = deserialize_value(serialized)
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)


def parse_user_value(raw, original_serialized, variable_name):
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None
    original_type = value_type(original_serialized)
    if variable_name in TEXT_IDENTIFIERS or original_type in {"string", "formula"}:
        return text
    if original_type == "bool":
        lowered = text.casefold()
        if lowered in {"oui", "true", "1", "vrai"}:
            return True
        if lowered in {"non", "false", "0", "faux"}:
            return False
        raise ValueError("Saisissez Oui ou Non.")
    if original_type in {"date", "datetime"}:
        try:
            return datetime.fromisoformat(text) if original_type == "datetime" else date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("Date invalide. Format attendu : AAAA-MM-JJ.") from exc
    normalized = re.sub(r"[\s\u00a0\u202f]", "", text).replace(",", ".")
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return text
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def values_equal(left_serialized, right_serialized):
    return deserialize_value(left_serialized) == deserialize_value(right_serialized)
