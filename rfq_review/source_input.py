"""Bounded user input for the existing single-item key/value quote contract."""
import datetime
import hashlib
import re

from . import extraction

MAX_SOURCE_BYTES = 12000
MAX_CUSTOM_OFFERS = 5


def validate_source(content, item_id):
    if not isinstance(content, str) or not 1 <= len(content.encode("utf-8")) <= MAX_SOURCE_BYTES:
        raise ValueError("invalid_source_size")
    if any(ord(char) < 32 and char not in "\r\n" for char in content):
        raise ValueError("invalid_source_control")
    labels = ("RFQ item", "Supplier") + extraction.LABELS
    cells = {}
    for line in content.splitlines():
        match = re.fullmatch(r"([^:]+):[ ]?(.*)", line)
        if not match:
            raise ValueError("invalid_source_row")
        label, value = match.groups()
        if label not in labels or label in cells or len(value) > 500:
            raise ValueError("invalid_source_field")
        cells[label] = value
    if set(cells) != set(labels) or cells["RFQ item"] != item_id:
        raise ValueError("invalid_source_coverage")
    if not re.fullmatch(r"NEW-[A-Z0-9_-]{1,32}", cells["Supplier"]):
        raise ValueError("invalid_custom_supplier")
    enums = {"Currency": {"KRW"}, "Order unit": {"each", "pack"},
             "MOQ unit": {"each", "pack"}, "Order multiple unit": {"each", "pack"},
             "Freight status": {"included", "fixed_per_order", "unknown"},
             "Other mandatory charge status": {"none_explicit", "unknown"},
             "Tax status": {"tax_excluded", "tax_included", "unknown"},
             "Lead time type": {"absolute_date", "conditional", ""}}
    for label, allowed in enums.items():
        if cells[label] not in allowed:
            raise ValueError("invalid_source_enum")
    for field, label in zip(extraction.FIELDS, extraction.LABELS):
        if field in extraction.NUMBERS:
            value = cells[label]
            if field == "freight_amount_krw" and value == "":
                continue
            if not re.fullmatch(r"(?:0|[1-9][0-9]*)", value) or len(value) > 30:
                raise ValueError("invalid_source_number")
            if int(value) < (0 if field == "freight_amount_krw" else 1):
                raise ValueError("invalid_source_number")
    unit = cells["Order unit"]
    if cells["MOQ unit"] != unit or cells["Order multiple unit"] != unit:
        raise ValueError("inconsistent_source_units")
    if unit == "each" and cells["Units per order unit"] != "1":
        raise ValueError("inconsistent_source_pack")
    if cells["Freight status"] == "fixed_per_order" and not cells["Freight amount KRW"]:
        raise ValueError("missing_fixed_freight")
    if cells["Freight status"] in {"included", "unknown"} and cells["Freight amount KRW"] not in {"", "0"}:
        raise ValueError("conflicting_freight")
    for label in ("Valid until", "Delivery date"):
        value = cells[label]
        if label == "Delivery date" and value == "" and cells["Lead time type"] != "absolute_date":
            continue
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("invalid_source_date")
        datetime.date.fromisoformat(value)
    if cells["Lead time type"] != "absolute_date" and cells["Delivery date"]:
        raise ValueError("conflicting_delivery")
    if cells["Lead time type"] == "conditional" and not cells["Lead time condition"]:
        raise ValueError("missing_delivery_condition")
    return cells["Supplier"], hashlib.sha256(content.encode("utf-8")).hexdigest()
