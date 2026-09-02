"""
استخراج الإيجار الفعلي من وصف الإعلان بالكامل عبر Regex -- بدون أي استدعاء
API، صفر تكلفة. يغطي كل الصيغ الشائعة اللي واجهناها بالبيانات الحقيقية.

يضيف عمودين جديدين:
- actual_annual_rent: الإيجار السنوي المستخرج (أو None)
- yield_pct: العائد المحسوب (إيجار ÷ سعر × 100)
"""

import pandas as pd
import os
import re

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "listings_sale_normal.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "rented_extracted_no_api.csv")


RENTED_HINTS = re.compile(
    r"مؤجرة|مؤجر\b|مؤجّرة|مؤجّر\b|"
    r"يوجد مستأجر|مستأجر حاليًا|مستأجر حاليا|"
    r"عقد إيجار ساري|عقد ايجار ساري|"
    r"عقد إيجار سنوي|عقد ايجار سنوي|"
    r"دخل ثابت|دخل إيجاري|دخل سنوي",
    re.IGNORECASE,
)

# أرقام عربية-هندية -> أرقام عادية
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(text):
    return text.translate(ARABIC_DIGITS)


# رقم عام: يقبل فواصل غربية/عربية، نقاط كفاصل آلاف، أرقام متتالية
NUM = r"[\d,،٬.]+"


def parse_amount(raw, context):
    """يحوّل رقم نصي (بأي صيغة: فواصل غربية/عربية، نقاط، ألف، k) لرقم فعلي"""
    raw = normalize_digits(raw)
    # نحذف كل فواصل الآلاف (غربية وعربية ونقطة) -- النقطة هنا فاصل آلاف
    # مو عشري (الأسعار والإيجارات عندنا أرقام صحيحة دائمًا)
    raw = re.sub(r"[,،٬.]", "", raw)
    try:
        amount = float(raw)
    except ValueError:
        return None
    if amount < 1000 and re.search(r"ألف|الف|[kK]\b", context):
        amount *= 1000
    return amount


def extract_annual_rent(description, price):
    """يستخرج الإيجار السنوي بترتيب أولوية -- من الأدق للأعم"""
    if not isinstance(description, str) or not description.strip():
        return None, "لا يوجد وصف"

    text = normalize_digits(description)
    # نوحّد علامات الترقيم اللي ممكن تكسر \s* (نقطتين، شرطة...) لمسافة
    text = re.sub(r"[:：]", " ", text)

    # ── أولوية 1: نسبة من سعر البيع ──────────────────────────────────
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%?٪?\s*(?:من\s*(?:قيمة\s*)?(?:البيع|السعر)|عائد\s*سنوي)", text)
    if pct_match and price and ("من" in pct_match.group(0) or "عائد" in pct_match.group(0)):
        pct = float(pct_match.group(1))
        if "من" in pct_match.group(0):  # بس نطبّق النسبة لو صريحة "من السعر"
            return round(price * pct / 100), "نسبة من سعر البيع"

    # ── أولوية 2: خيارين بديلين لطريقة السداد ────────────────────────
    alt_pattern = re.search(
        rf"({NUM})\s*(?:ألف|الف)?\s*(?:ريال)?\s*دفعة\s*(?:واحدة|واحده)?"
        rf"\s*(?:و|/|-)\s*({NUM})\s*(?:ألف|الف)?\s*(?:ريال)?\s*دفعتين",
        text
    )
    if alt_pattern:
        ctx = text[max(0, alt_pattern.start()-15):alt_pattern.end()+15]
        a1 = parse_amount(alt_pattern.group(1), ctx)
        a2 = parse_amount(alt_pattern.group(2), ctx)
        if a1 and a2:
            return min(a1, a2), "دفعة واحدة/دفعتين (خيار بديل، أخذنا الأصغر)"

    # ── أولوية 3: إيجار شهري صريح -- نضربه × 12 ──────────────────────
    monthly_patterns = [
        rf"(?:مؤجرة|مؤجر)?\s*(?:شهريًا|شهريا|بعقد\s*شهري|دفع\s*شهري)"
        rf"\s*(?:بقيمة|ب)?\s*({NUM})\s*(?:ألف|الف|[kK])?\s*ريال?",
        rf"({NUM})\s*(?:ألف|الف|[kK])?\s*ريال?\s*شهريًا",
    ]
    for pat in monthly_patterns:
        m = re.search(pat, text)
        if m:
            ctx = text[max(0, m.start()-15):m.end()+15]
            amount = parse_amount(m.group(1), ctx)
            if amount:
                return round(amount * 12), "إيجار شهري صريح × 12"

    # ── أولوية 4: "على دفعتين" أو "كل 6 أشهر" -- إجمالي سنوي كامل ────
    installment_pattern = re.search(
        rf"({NUM})\s*(?:ألف|الف)?\s*(?:ريال)?\s*(?:سنوي(?:ًا|ا)?\s*)?"
        rf"(?:على\s*)?(?:دفعتين|كل\s*6\s*(?:أشهر|شهور)|نصف\s*سنوي)",
        text
    )
    if installment_pattern:
        ctx = text[max(0, installment_pattern.start()-15):installment_pattern.end()+15]
        amount = parse_amount(installment_pattern.group(1), ctx)
        if amount:
            return amount, "على دفعتين (إجمالي سنوي، بدون مضاعفة)"

    # ── أولوية 5: إيجار سنوي/عام صريح بأي صياغة (مؤجرة أو تؤجر) ──────
    annual_patterns = [
        rf"(?:الإيجار|الدخل)\s*السنوي\s*(?:المتوقع|الحالي)?\s*({NUM})\s*(?:ألف|الف)?\s*ريال",
        rf"دخل\s*سنوي\s*({NUM})\s*(?:ألف|الف)?\s*ريال",
        rf"(?:مؤجرة|مؤجر|تؤجر)[^\d]{{0,30}}?(?:بمبلغ|ب|بعقد|بقيمة|بحوالي)?\s*({NUM})\s*(?:ألف|الف|[kK])\b",
        rf"(?:مؤجرة|مؤجر|تؤجر)[^\d]{{0,30}}?(?:بمبلغ|ب|بعقد|بقيمة|بحوالي)?\s*({NUM})\s*ريال",
    ]
    for pattern in annual_patterns:
        m = re.search(pattern, text)
        if m:
            ctx = text[max(0, m.start()-15):m.end()+15]
            amount = parse_amount(m.group(1), ctx)
            if amount and amount > 1000:
                return amount, "إيجار سنوي صريح"

    # ── أولوية 6 (احتياطي أخير): رقم بعد "بعقد/بمبلغ/بقيمة" بدون كلمة
    # ريال أو ألف صراحة -- بس نشترط رقم كبير (4 أرقام فأكثر) لتفادي
    # التقاط أرقام عشوائية (عدد غرف، عمر...)
    fallback_pattern = re.search(
        rf"(?:مؤجرة|مؤجر|تؤجر)[^\d]{{0,20}}?(?:بعقد|بمبلغ|بقيمة)\s*({NUM})\b",
        text
    )
    if fallback_pattern:
        ctx = text[max(0, fallback_pattern.start()-15):fallback_pattern.end()+15]
        amount = parse_amount(fallback_pattern.group(1), ctx)
        if amount and amount >= 5000:
            return amount, "إيجار سنوي صريح (احتياطي، بدون كلمة ريال)"

    return None, "ما لقينا رقم واضح"


def sanity_check_rent(annual_rent, price):
    """فحص منطقي أخير: يرفض أرقام مستحيلة (تطابق السعر أو عائد >20%)"""
    if not annual_rent or not price:
        return annual_rent
    ratios = [1.0, 0.75, 0.5, 0.25, 0.9, 0.95]
    if any(abs(annual_rent - price * r) / price < 0.03 for r in ratios):
        return None
    if annual_rent / price * 100 > 20:
        return None
    return annual_rent


def normalize_for_duplicate_check(description):
    """يطبّع الوصف لمقارنة تكرار دقيقة -- يشيل فروقات سطحية (مسافات زايدة،
    أرقام جوال متغيرة، إيموجي) اللي ممكن تخلي نفس الإعلان يبان مختلف شكليًا"""
    if not isinstance(description, str):
        return ""
    text = description
    # نشيل أرقام طويلة (جوالات، تراخيص) -- غالبًا الشي الوحيد المختلف بين نسخ نفس الإعلان
    text = re.sub(r"\d{7,}", "", text)
    # نوحّد كل المسافات المتعددة/الأسطر لمسافة وحدة
    text = re.sub(r"\s+", " ", text).strip()
    # نشيل الإيموجي ورموز التنسيق الشائعة
    text = re.sub(r"[✨📍📐📅💰📈🏢▪️🛏️🛋️🍳💎✔️🚀📞💼🔹🏷️⭕️🔐🌿]", "", text)
    return text


def main():
    if not os.path.exists(INPUT_PATH):
        print(f"تحذير: ما لقيت {INPUT_PATH}")
        return

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"إجمالي الإعلانات: {len(df)}")

    mask = df["description"].fillna("").astype(str).str.contains(RENTED_HINTS, na=False)
    candidates = df[mask].copy()
    print(f"مرشّحين (يذكرون تأجير): {len(candidates)}")

    rents, reasons = [], []
    for _, row in candidates.iterrows():
        rent, reason = extract_annual_rent(row.get("description"), row.get("price"))
        rent = sanity_check_rent(rent, row.get("price"))
        rents.append(rent)
        reasons.append(reason)

    candidates["actual_annual_rent"] = rents
    candidates["rent_extraction_note"] = reasons
    candidates["yield_pct"] = candidates.apply(
        lambda r: round(r["actual_annual_rent"] / r["price"] * 100, 2)
        if pd.notna(r["actual_annual_rent"]) and r.get("price") else None,
        axis=1
    )

    with_rent = candidates["actual_annual_rent"].notna().sum()
    print(f"لقينا رقم إيجار موثوق: {with_rent} من {len(candidates)}")

    # كشف التكرار: نفس الوصف (بعد التطبيع) برقم إعلان مختلف -- يعني نفس
    # العقار أُعيد نشره أو نسخ من وسيط لوسيط
    candidates["_normalized_desc"] = candidates["description"].apply(normalize_for_duplicate_check)
    dup_counts = candidates.groupby("_normalized_desc")["_normalized_desc"].transform("count")
    candidates["is_duplicate_listing"] = dup_counts > 1
    candidates["duplicate_group_size"] = dup_counts
    candidates = candidates.drop(columns=["_normalized_desc"])

    dup_count = candidates["is_duplicate_listing"].sum()
    print(f"إعلانات مكررة (نفس الوصف، رقم إعلان مختلف): {dup_count}")

    candidates = candidates.sort_values("yield_pct", ascending=False, na_position="last")

    cols = [c for c in ["listing_id", "url", "title", "district", "direction", "price",
                          "area_sqm", "rooms", "bathrooms", "age_years",
                          "actual_annual_rent", "yield_pct", "rent_extraction_note",
                          "is_duplicate_listing", "duplicate_group_size",
                          "description"] if c in candidates.columns]
    candidates = candidates[cols]

    candidates.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
