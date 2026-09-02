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
    r"عقد اجار|عقد إجار|"  # صياغة بدون همزة، شائعة
    r"دخل ثابت|دخل إيجاري|دخل سنو|"  # "دخل سنو" يلقط "سنوي" و"سنو" (خطأ إملائي) مع بعض
    r"قيمة الايجار|قيمة الإيجار|"
    r"عائد سنوي",
    re.IGNORECASE,
)

# أرقام عربية-هندية -> أرقام عادية
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(text):
    return text.translate(ARABIC_DIGITS)


# رقم عام: يقبل فواصل غربية/عربية، نقاط كفاصل آلاف، أرقام متتالية
NUM = r"[\d,،٬.]+"


def safe_gap(size):
    """فجوة آمنة بين كلمة مؤجرة والرقم -- تمنع الفجوة من احتواء كلمات تدل
    على انتقال لموضوع ثاني (سعر البيع، السوم...) عشان ما نلقط رقم سعر
    البيع بالغلط ظانّين إنه إيجار (خطأ حقيقي صار: "مؤجرة ... سعر الشقة
    مليون و200 الف" -- استخرج 200 ألف كإيجار غلط)"""
    return rf"(?:(?!سعر|بيع|البيع|السوم|المطلوب|الحد)[^\d]){{0,{size}}}?"


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
    # نشيل علامات التشكيل العربية (شدة، تنوين، فتحة...) -- تحل مشاكل كثيرة
    # دفعة وحدة (مثال: "مؤجّرة" بشدة تصير "مؤجرة"، "حاليًا" و"حالياً" تتوحّدان)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    # نوحّد علامات الترقيم اللي ممكن تكسر \s* (نقطتين، شرطة...) لمسافة
    text = re.sub(r"[:：]", " ", text)
    # نوحّد الأقواس والنجوم (تنسيق شائع بالإعلانات) لمسافة -- تمنعها من كسر
    # التطابق بين الرقم والكلمات المحيطة به
    text = re.sub(r"[()（）*\[\]]", " ", text)
    # نوحّد اختصار "ر.س" (ريال سعودي) لكلمة "ريال" -- بعض الإعلانات تستخدمه بدل الكلمة كاملة
    text = re.sub(r"ر\.\s*س\b", "ريال", text)

    # ── أولوية 1: نسبة من سعر البيع ──────────────────────────────────
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%?٪?\s*(?:من\s*(?:قيمة\s*)?(?:البيع|السعر)|عائد\s*سنوي)", text)
    if pct_match and price and ("من" in pct_match.group(0) or "عائد" in pct_match.group(0)):
        pct = float(pct_match.group(1))
        if "من" in pct_match.group(0):  # بس نطبّق النسبة لو صريحة "من السعر"
            return round(price * pct / 100), "نسبة من سعر البيع"

    # نمط معكوس: "عائد X% سنوي" أو "بعائد X%" (الكلمة قبل الرقم، مو بعده)
    reverse_pct_match = re.search(r"عائد[^\d%٪]{0,10}?(\d+(?:\.\d+)?)\s*%?٪", text)
    if reverse_pct_match and price:
        pct = float(reverse_pct_match.group(1))
        if 2 <= pct <= 20:  # فحص منطقي: عائد إيجاري معقول، مو رقم عشوائي
            return round(price * pct / 100), "نسبة عائد سنوي (صيغة معكوسة)"

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

    # ── أولوية 2.5: إيجار سنوي صريح مرتبط مباشرة بـ"مؤجرة" (قبل فحص
    # الشهري) -- يمنع التقاط دخل إضافي غير متعلق بالعقار (زي إيجار برج
    # اتصالات) لو صادف وجود كلمة "شهريًا" بمكان ثاني بالنص
    direct_annual_pattern = re.search(
        rf"مؤجرة\s*سنويا?\s*({NUM})\s*(?:ألف|الف)?\s*ريال",
        text
    )
    if direct_annual_pattern:
        ctx = text[max(0, direct_annual_pattern.start()-15):direct_annual_pattern.end()+15]
        amount = parse_amount(direct_annual_pattern.group(1), ctx)
        if amount:
            return amount, "إيجار سنوي صريح مرتبط بمؤجرة مباشرة (أولوية قصوى)"

    # ── أولوية 3: إيجار شهري صريح -- نضربه × 12 ──────────────────────
    monthly_patterns = [
        rf"(?:مؤجرة|مؤجر)?\s*(?:شهريًا|شهريا|بعقد\s*شهري|دفع\s*شهري)"
        rf"\s*(?:بقيمة|ب)?\s*({NUM})\s*(?:ألف|الف|[kK])?\s*(?:ريال)?",
        rf"({NUM})\s*(?:ألف|الف|[kK])?\s*(?:ريال)?\s*(?:شهريًا|شهريا)",
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
        rf"(?:الإجمالي|الاجمالي)\s*السنوي\s*({NUM})\s*(?:ألف|الف)?\s*(?:ريال)?",  # "الإجمالي السنوي 54 الف" -- أقوى من أي رقم شهري بنفس النص
        rf"دخل\s*سنو[ي]?\s*({NUM})\s*(?:ألف|الف)?\s*(?:ريال)?",  # "دخل سنو" أو "دخل سنوي" (خطأ إملائي شائع)، ريال اختياري
        rf"قيمة\s*(?:عقد\s*)?ال(?:إيجار|ايجار)(?:\s*الحالي(?:ة|ه)?)?\s*(?:السنوي)?\s*({NUM})\s*(?:ألف|الف)?\s*(?:ريال)?",
        rf"عقد\s*(?:اجار|إجار|ايجار|إيجار){safe_gap(15)}({NUM})\s*(?:ألف|الف)?\s*(?:ريال)?\s*سنوي",
        rf"(?:مؤجرة|مؤجر|تؤجر){safe_gap(30)}(?:بمبلغ|ب|بعقد|بقيمة|بحوالي|بسعر)?\s*({NUM})\s*(?:ألف|الف|[kK])?\s*(?:ريال)?\s*في\s*السنة",
        rf"(?:مؤجرة|مؤجر|تؤجر){safe_gap(30)}(?:بمبلغ|ب|بعقد|بقيمة|بحوالي|بسعر)?\s*({NUM})\s*(?:ألف|الف|[kK])\b",
        rf"(?:مؤجرة|مؤجر|تؤجر){safe_gap(30)}(?:بمبلغ|ب|بعقد|بقيمة|بحوالي|بسعر)?\s*({NUM})\s*(?:ريال|﷼)",
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
    fallback_patterns = [
        rf"(?:مؤجرة|مؤجر|تؤجر){safe_gap(20)}(?:بعقد|بمبلغ|بقيمة|بسعر)\s*({NUM})\b",
        # "مؤجرة بـ X لسنة واحدة" -- بدون كلمة ريال، بس مع مؤشر سنوي واضح
        rf"(?:مؤجرة|مؤجر){safe_gap(15)}({NUM})\s*(?:ألف|الف|[kK])?\s*لسنة\s*واحدة",
        # رقم مباشر بعد "مؤجرة بـ/ب" بدون أي كلمة وسيطة (آخر احتياط، رقم كبير بس)
        rf"(?:مؤجرة|مؤجر)\s*(?:حاليًا|حاليا|حالياً)?\s*ب\s*({NUM})\b",
        # رقم مباشر بعد "مؤجرة" بدون أي حرف جر أو كلمة وسيطة إطلاقًا (زي "مؤجرة 87000")
        rf"(?:مؤجرة|مؤجر)\s+({NUM})\b(?!\s*شهر|\s*سنة|\s*يوم)",
    ]
    for fallback_pattern_str in fallback_patterns:
        fallback_pattern = re.search(fallback_pattern_str, text)
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


# قائمة الخصائص الشائعة -- كل عنصر (التسمية الموحّدة، نمط الكشف) بترتيب
# منطقي. النمط يبحث بالوصف، ولو طابق نضيف التسمية الموحّدة لقائمة الخصائص
FEATURE_PATTERNS = [
    ("دخول ذكي", r"دخول\s*ذكي|سمارت\s*هوم|smart\s*home|نظام\s*ذكي"),
    ("مصعد", r"مصعد|أسانسير|اصنصير"),
    ("موقف خاص", r"موقف\s*(?:سيارة\s*)?خاص|موقف\s*خارجي\s*خاص|موقف\s*بالقبو|موقف\s*بدروم"),
    ("مطبخ راكب", r"مطبخ\s*راكب|مطبخ\s*مجهز|مطبخ\s*متكامل|مطبخ\s*مركّب|مطبخ\s*مركب"),
    ("مكيفات راكبة", r"مكيفات\s*راكبة|مكيفات\s*سبليت|مكيفات\s*سبلت|تكييف\s*مركزي|تكييف\s*راكب|مكيفات\s*مركزية"),
    ("اتحاد ملاك", r"اتحاد\s*ملاك|جمعية\s*ملاك"),
    ("حوش خاص", r"حوش\s*(?:خاص|خلفي|جانبي)?|ارتداد"),
    ("سطح خاص", r"سطح\s*خاص|سطح\s*(?:كبير|واسع)"),
    ("كاميرات مراقبة", r"كاميرات\s*مراقبة|نظام\s*أمني|كاميرات\s*خارجية"),
    ("نادي رياضي", r"نادي\s*رياضي|جيم\b|GYM"),
    ("مسبح", r"مسبح|مسابح"),
    ("حضانة أطفال", r"حضانة\s*أطفال|روضة\s*أطفال|حاضنة\s*أطفال"),
    ("بلكونة", r"بلكونة|بلكونتان|بلكونتين"),
    ("تشطيب فاخر", r"تشطيب\s*فاخر|تشطيبات\s*فاخرة|تشطيب\s*راقي"),
    ("عداد كهرباء مستقل", r"عداد\s*كهرباء\s*مستقل|عداد\s*كهرب\s*مستقل"),
    ("عداد ماء مستقل", r"عداد\s*(?:ماء|مياه)\s*مستقل"),
    ("مؤثثة", r"مؤثثة|مفروشة|أثاث\s*فاخر|أثاث\s*كامل"),
    ("غرفة خادمة", r"غرفة\s*خادمة|غرفة\s*عاملة|غرفة\s*خدمات"),
    ("مستودع", r"مستودع|مخزن"),
    ("مدخل خاص", r"مدخل\s*خاص|مدخل\s*مستقل"),
    ("ألياف ضوئية", r"ألياف\s*ضوئية|فايبر"),
    ("خزان مستقل", r"خزان\s*(?:مياه\s*)?مستقل|خزان\s*(?:أرضي|علوي)\s*(?:و(?:أرضي|علوي)\s*)?مستقل"),
    ("دور أرضي", r"دور\s*أرضي|الدور\s*الأرضي"),
    ("صك مستقل", r"صك\s*(?:مستقل|إلكتروني|حر)"),
    ("رهن عقاري", r"مرهون|رهن\s*عقاري|عليها\s*رهن"),
    ("قريب من الخدمات", r"قريب(?:ة)?\s*من\s*(?:جميع\s*)?الخدمات|قريب(?:ة)?\s*من\s*محطة\s*المترو"),
]


def extract_key_features(description):
    """يستخرج أهم خصائص العقار من الوصف عبر Regex -- بدون أي API. يرجع
    قائمة مفصولة بـ | بنفس أسلوب الأمثلة (دخول ذكي | موقف خاص | مصعد...)"""
    if not isinstance(description, str) or not description.strip():
        return ""
    text = normalize_digits(description)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)

    found = []
    for label, pattern in FEATURE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(label)

    return " | ".join(found)


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
    candidates["key_features"] = candidates["description"].apply(extract_key_features)

    with_rent = candidates["actual_annual_rent"].notna().sum()
    print(f"لقينا رقم إيجار موثوق: {with_rent} من {len(candidates)}")

    # حذف التكرار: نفس الوصف (بعد التطبيع) برقم إعلان مختلف -- يعني نفس
    # العقار أُعيد نشره أو نسخ من وسيط لوسيط -- نبقي نسخة وحدة بس (الأولى)
    candidates["_normalized_desc"] = candidates["description"].apply(normalize_for_duplicate_check)
    before_dedup = len(candidates)
    candidates = candidates.drop_duplicates(subset="_normalized_desc", keep="first")
    candidates = candidates.drop(columns=["_normalized_desc"])
    removed = before_dedup - len(candidates)
    print(f"حذفنا {removed} إعلان مكرر (نفس الوصف، رقم إعلان مختلف)")

    # ترتيب بمستويين: (1) اللي له عائد محسوب -- تنازليًا حسب العائد
    # (2) اللي مؤجّر بدون عائد صريح -- حسب العمر من الأجدد للأقدم (القديم آخر شي)
    candidates["_has_yield"] = candidates["yield_pct"].notna()
    candidates = candidates.sort_values(
        ["_has_yield", "yield_pct", "age_years"],
        ascending=[False, False, True],
        na_position="last"
    ).drop(columns=["_has_yield"])

    cols = [c for c in ["listing_id", "url", "title", "district", "direction", "price",
                          "area_sqm", "rooms", "bathrooms", "age_years",
                          "actual_annual_rent", "yield_pct", "key_features",
                          "description"] if c in candidates.columns]
    candidates = candidates[cols]

    # تنسيق فواصل الآلاف للأرقام الكبيرة (السعر والإيجار) -- يسهّل القراءة
    # بإكسل. نحوّلها لنص منسّق، فيبقى العمود الرقمي يقرأ صح لو احتجته لاحقًا
    for col in ["price", "actual_annual_rent"]:
        if col in candidates.columns:
            candidates[col] = candidates[col].apply(
                lambda v: f"{v:,.0f}" if pd.notna(v) else v
            )

    # تنسيق العائد كنسبة مئوية بعلامة % صريحة
    if "yield_pct" in candidates.columns:
        candidates["yield_pct"] = candidates["yield_pct"].apply(
            lambda v: f"{v:.2f}%" if pd.notna(v) else v
        )

    candidates.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
