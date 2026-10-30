"""Números de interface pt-BR / en-US; valores ausentes continuam ausentes."""
import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation


def normalize(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value)) if not unicodedata.combining(c)).lower().strip()


def parse_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) and value >= 0 else None
    text = normalize(value).replace("\u00a0", " ").replace("\u202f", " ").strip()
    match = re.fullmatch(r"(\d[\d\s.,]*)\s*(milhoes|milhao|mil|mi|k|m)?", text)
    if not match:
        return None
    number, suffix = match.groups()
    number = number.replace(" ", "")
    multiplier = {"k": 1000, "mil": 1000, "m": 1000000, "mi": 1000000, "milhao": 1000000, "milhoes": 1000000}.get(suffix, 1)
    if "," in number and "." in number:
        decimal = "," if number.rfind(",") > number.rfind(".") else "."
        number = number.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in number or "." in number:
        separator = "," if "," in number else "."
        chunks = number.split(separator)
        if not suffix and len(chunks) > 1 and all(len(x) == 3 for x in chunks[1:]):
            number = "".join(chunks)
        elif len(chunks) == 2:
            number = number.replace(separator, ".")
        else:
            return None
    try:
        result = Decimal(number) * multiplier
        return int(result) if result == result.to_integral_value() else float(result)
    except InvalidOperation:
        return None
