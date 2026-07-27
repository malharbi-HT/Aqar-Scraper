"""
دوال استخراج وتصحيح السعر من نص الوصف -- نسخة الإيجار.
يُستورد كوحدة من clean_rent_data.py، ما يشتغل لحاله.
"""

import pandas as pd
import re

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(text):
    return str(text or "").translate(ARABIC_DIGITS)


# نمط "الإيجار/السعر [:  ] X [الف/مليون] [ريال]" -- للأرقام المختصرة
PRICE_PATTERN = re.compile(
    r"(?:الإيجار|الايجار|إيجار|ايجار|السعر)\s*[:\s]*(\d{1,4}(?:[.,]\d+)?)\s*(الف|ألف|مليون)?\s*(?:ريال|ر\.س|﷼)?"
)

PRICE_FULL_NUMBER_PATTERN = re.compile(
    r"(?:الإيجار|الايجار|إيجار|ايجار|السعر)\s*[:\s]*\[?(\d{1,3}(?:[,.]\d{3}){1,3})\]?(?!\d)\s*(?:ريال|ر\.س|﷼)?"
)

PRICE_PLAIN_NUMBER_PATTERN = re.compile(
    r"(?:الإيجار|الايجار|إيجار|ايجار|السعر)\s*[:\s]*(\d{4,7})(?!\d)"
)

# كلمات تدل إن السعر القريب يخص البيع لا الإيجار -- نستثنيها (عكس منطق البيع)
SALE_KEYWORDS = ("البيع", "للبيع", "بيع")

# طلبات تسويق (مو إعلانات عقار حقيقية)
MARKETING_REQUEST_KEYWORDS = ("طلب تسويق", "طلب تسويقي")

# كلمات تدل إن إعلان "الإيجار" فعليًا بيع متصنّف غلط
SALE_MISCLASSIFICATION_KEYWORDS = (
    "للبيع", "البيع كاش", "البيع نقدا", "سعر البيع", "يرغب البيع",
)


def is_marketing_request(description):
    desc = str(description or "")
    return any(kw in desc for kw in MARKETING_REQUEST_KEYWORDS)


def is_actually_sale(description):
    """يتحقق هل إعلان 'الإيجار' هذا فعليًا بيع متصنّف غلط"""
    desc = str(description or "")
    return any(kw in desc for kw in SALE_MISCLASSIFICATION_KEYWORDS)


def looks_like_wrong_price(row, extracted_price):
    price = row.get("price")
    if pd.isna(price) or extracted_price is None:
        return False
    price = float(price)
    ratio = price / extracted_price if extracted_price else 0
    return ratio > 2.0 or ratio < 0.5


def extract_price_from_description(description):
    """يحاول يستخرج سعر الإيجار الحقيقي من نص الوصف (يستثني أي ذكر لسعر البيع)"""
    desc = normalize_digits(description)
    candidates = []

    MAX_REALISTIC_RENT = 500_000  # فوق هذا الرقم، احتمال كبير إنه سعر بيع مو إيجار

    def is_near_sale_keyword(pos):
        window = desc[max(0, pos - 25):pos]
        return any(kw in window for kw in SALE_KEYWORDS)

    for m in PRICE_PATTERN.finditer(desc):
        if is_near_sale_keyword(m.start()):
            continue
        number_str, unit = m.group(1), m.group(2)
        value = float(number_str.replace(",", "."))
        if unit in ("الف", "ألف"):
            value *= 1_000
        elif unit == "مليون":
            value *= 1_000_000
        elif value < 1000:
            continue
        if 5_000 <= value <= MAX_REALISTIC_RENT:
            candidates.append((m.start(), value))

    for m in PRICE_FULL_NUMBER_PATTERN.finditer(desc):
        if is_near_sale_keyword(m.start()):
            continue
        value = float(m.group(1).replace(",", "").replace(".", ""))
        if 5_000 <= value <= MAX_REALISTIC_RENT:
            candidates.append((m.start(), value))

    if not candidates:
        for m in PRICE_PLAIN_NUMBER_PATTERN.finditer(desc):
            if is_near_sale_keyword(m.start()):
                continue
            value = float(m.group(1))
            if 5_000 <= value <= MAX_REALISTIC_RENT:
                candidates.append((m.start(), value))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]
