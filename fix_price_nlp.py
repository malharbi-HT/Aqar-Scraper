"""
يكتشف الصفوف اللي سعرها غير منطقي (على الأغلب من حقل بيانات خاطئ بالمصدر الأصلي،
مثل rega_total_price بدل السعر الفعلي)، ويحاول يستخرج السعر الصحيح من نص الوصف.
"""

import pandas as pd
import re
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "listings_sale_final.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "listings_sale_price_fixed.csv")

MAX_REALISTIC_PRICE = 20_000_000  # فوق هذا الرقم، احتمال كبير إنه خطأ مصدر بيانات

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(text):
    return str(text or "").translate(ARABIC_DIGITS)


# نمط "البيع/السعر [:  ] X [الف/مليون] [ريال]" -- للأرقام المختصرة
PRICE_PATTERN = re.compile(
    r"(?:البيع|السعر)\s*[:\s]*(\d{1,4}(?:[.,]\d+)?)\s*(الف|ألف|مليون)?\s*(?:ريال|ر\.س|﷼)?"
)

# نمط للأرقام الكاملة المفصولة بفواصل الآلاف (مثل "1,350,000") بدون اختصار
# نتحقق إن كل مجموعة أرقام بعد الفاصلة بالضبط 3 أرقام (وإلا فيه غلطة طباعية بالمصدر، نتجاهلها لتفادي استنتاج خاطئ)
PRICE_FULL_NUMBER_PATTERN = re.compile(
    r"(?:البيع|السعر)\s*[:\s]*\[?(\d{1,3}(?:[,.]\d{3}){1,3})\]?(?!\d)\s*(?:ريال|ر\.س|﷼)?"
)

# نمط رقم مباشر بدون أي فاصل فصل (مثل "السعر:550000")
PRICE_PLAIN_NUMBER_PATTERN = re.compile(
    r"(?:البيع|السعر)\s*[:\s]*(\d{5,7})(?!\d)"
)

# كلمات تدل إن السعر القريب يخص الإيجار لا البيع -- نستثنيها
RENT_KEYWORDS = ("الإيجار", "الايجار", "إيجار", "ايجار", "أجار", "اجار")

# كلمات تدل إن الإعلان فعليًا إيجار مصنّف غلط ضمن "للبيع"
RENTAL_MISCLASSIFICATION_KEYWORDS = (
    "إيجار شهري", "ايجار شهري", "إيجار سنوي", "ايجار سنوي",
    "ريال شهرياً", "ريال سنوياً", "ريال سنويا", "ريال شهريا",
)


# طلبات تسويق (مو إعلانات عقار حقيقية) -- نستثنيها بالكامل
MARKETING_REQUEST_KEYWORDS = ("طلب تسويق", "طلب تسويقي")


def is_marketing_request(description):
    desc = str(description or "")
    return any(kw in desc for kw in MARKETING_REQUEST_KEYWORDS)


def is_actually_rental(description):
    """يتحقق هل إعلان 'البيع' هذا فعليًا إيجار متصنّف غلط"""
    desc = str(description or "")
    return any(kw in desc for kw in RENTAL_MISCLASSIFICATION_KEYWORDS)


def looks_like_wrong_price(row, extracted_price):
    """يقارن السعر بالعمود مع السعر المستخرج من الوصف. لو الفرق كبير (أكثر من ضعفين
    بأي اتجاه) نعتبره خطأ محتمل، بغض النظر عن كون الرقم الأصلي 'معقول' الحجم أو لا."""
    price = row.get("price")
    if pd.isna(price) or extracted_price is None:
        return False
    price = float(price)
    ratio = price / extracted_price if extracted_price else 0
    return ratio > 2.0 or ratio < 0.5


def extract_price_from_description(description):
    """يحاول يستخرج سعر البيع الحقيقي من نص الوصف (يستثني أي ذكر لسعر الإيجار)"""
    desc = normalize_digits(description)
    candidates = []

    def is_near_rent_keyword(pos):
        """يتحقق هل الموضع قريب من كلمة 'الإيجار' -- لو نعم نتجاهل هذا الرقم"""
        window = desc[max(0, pos - 25):pos]
        return any(kw in window for kw in RENT_KEYWORDS)

    # النمط الأول: أرقام مختصرة (X الف / X مليون)
    for m in PRICE_PATTERN.finditer(desc):
        if is_near_rent_keyword(m.start()):
            continue
        number_str, unit = m.group(1), m.group(2)
        value = float(number_str.replace(",", "."))
        if unit in ("الف", "ألف"):
            value *= 1_000
        elif unit == "مليون":
            value *= 1_000_000
        elif value < 1000:
            continue
        if 30_000 <= value <= MAX_REALISTIC_PRICE:
            candidates.append((m.start(), value))

    # النمط الثاني: أرقام كاملة بفواصل آلاف أو نقاط (مثل "1,350,000" أو "1.600.000")
    for m in PRICE_FULL_NUMBER_PATTERN.finditer(desc):
        if is_near_rent_keyword(m.start()):
            continue
        value = float(m.group(1).replace(",", "").replace(".", ""))
        if 30_000 <= value <= MAX_REALISTIC_PRICE:
            candidates.append((m.start(), value))

    # النمط الثالث: رقم مباشر بدون أي فاصل (مثل "السعر:550000")
    if not candidates:
        for m in PRICE_PLAIN_NUMBER_PATTERN.finditer(desc):
            if is_near_rent_keyword(m.start()):
                continue
            value = float(m.group(1))
            if 30_000 <= value <= MAX_REALISTIC_PRICE:
                candidates.append((m.start(), value))

    if not candidates:
        return None
    # ناخذ أقرب مطابقة لبداية النص (عادة أول ذكر للسعر هو الأدق والأوثق)
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def main():
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"عدد الصفوف: {len(df)}")

    # نحذف طلبات التسويق (مو إعلانات عقار حقيقية)
    df["is_marketing"] = df["description"].apply(is_marketing_request)
    marketing_count = df["is_marketing"].sum()
    print(f"طلبات تسويق (سنحذفها، مو إعلانات حقيقية): {marketing_count}")
    df = df[~df["is_marketing"]].drop(columns=["is_marketing"])

    # نكتشف ونحذف إعلانات "بيع" اللي هي فعليًا إيجار متصنّف غلط
    df["is_actually_rental"] = df["description"].apply(is_actually_rental)
    rental_count = df["is_actually_rental"].sum()
    print(f"إعلانات إيجار متصنّفة غلط ضمن البيع (سنحذفها): {rental_count}")
    df = df[~df["is_actually_rental"]].drop(columns=["is_actually_rental"])
    print(f"عدد الصفوف بعد الحذف: {len(df)}")

    print("نستخرج السعر من وصف كل صف (يستغرق شوي)...")
    df["_extracted_price"] = df["description"].apply(extract_price_from_description)

    df["is_price_error"] = df.apply(
        lambda row: looks_like_wrong_price(row, row["_extracted_price"]), axis=1
    )

    # حد أدنى مطلق: أي سعر تحت هذا الرقم مستحيل يكون سعر عقار حقيقي بالرياض
    # (حتى لو ما قدرنا نستخرج بديل، لازم نفرّغه بدل ما يبقى رقم مستحيل)
    ABSOLUTE_MIN_PRICE = 50_000
    absurdly_low = df["price"] < ABSOLUTE_MIN_PRICE
    df.loc[absurdly_low, "is_price_error"] = True

    flagged = df[df["is_price_error"]]
    print(f"صفوف فيها احتمال خطأ بمصدر السعر (فرق أكثر من ضعفين): {len(flagged)}")

    df["price_corrected"] = df["price"]
    df.loc[df["is_price_error"], "price_corrected"] = df.loc[
        df["is_price_error"], "_extracted_price"
    ]
    fixed_count = df["is_price_error"].sum()

    df = df.drop(columns=["_extracted_price"])

    print(f"تم تصحيح السعر تلقائيًا لـ {fixed_count} صف")

    sample = df[df["is_price_error"]][["listing_id", "price", "price_corrected"]].head(20)
    print("\n--- عينة للمراجعة ---")
    print(sample.to_string(index=False))

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nتم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
