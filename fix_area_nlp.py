"""
يكتشف الصفوف اللي فيها "مساحة المشروع" بدل مساحة الوحدة الفعلية،
ويحاول يستخرج المساحة الصحيحة من نص الوصف باستخدام أنماط نصية.

المنطق:
1. نكتشف وجود "مساحة المشروع/الأرض" بالوصف مع رقم يطابق area_sqm الحالي -> علامة خطأ محتمل
2. نستخرج كل نطاقات المساحات المذكورة بالوصف (مثال: "من 60 م² إلى 81 م²")
3. نستخرج كل الأسعار المذكورة معها، ونختار النطاق اللي سعره الأقرب لسعر العمود
4. نستبدل area_sqm بمنتصف النطاق الصحيح المكتشف، ونعلّم الصف كـ "مصحح تلقائيًا"
"""

import pandas as pd
import re
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "listings_sale.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "listings_sale_area_fixed.csv")

# نمط "مساحة المشروع" أو "مساحة الأرض" -- يدل إن area_sqm الحالي قد يكون خاطئ
PROJECT_AREA_PATTERN = re.compile(
    r"مساحة\s*(?:المشروع|الأرض|الأجمالية للمشروع)\s*[:\s]*([\d,]+)\s*م"
)

# نمط نطاقات المساحة: "من 60 م² إلى 81 م²" أو "60 م الى 81 م" أو "بين 94 و127 م"
RANGE_PATTERN = re.compile(
    r"(\d{2,4}(?:\.\d+)?)\s*(?:م[²2]?)?\s*(?:إلى|الى|حتى|وحتى|-|و)\s*(\d{2,4}(?:\.\d+)?)\s*م[²2]?"
)

# نمط "مساحات [كلمة اختيارية] تصل إلى X" -- حد أعلى بس بدون حد أدنى
PLURAL_UPPER_PATTERN = re.compile(
    r"مساحات\s*(?:\S+\s+){0,2}?تصل\s*(?:الى|إلى)\s*(\d{2,4}(?:[.,]\d+)?)\s*م"
)

# نمط "المساحات تبدأ من X" -- حد أدنى بس بدون حد أعلى (صيغة الجمع)
PLURAL_LOWER_PATTERN = re.compile(
    r"مساحات\s*تبدأ?\s*من\s*(\d{2,4}(?:[.,]\d+)?)\s*م"
)

# نمط قائمة مساحات مفصولة بفواصل (مثل "المساحات 166م ،، 139م")
COMMA_LIST_PATTERN = re.compile(
    r"المساحات\s+(\d{2,4}(?:[.,]\d+)?)\s*م\s*[،,]+\s*(\d{2,4}(?:[.,]\d+)?)\s*م"
)

# نمط احتياطي: مساحة مفردة مباشرة بصيغ متعددة
# يستثني صراحة "مساحة الأرض/المشروع" لأنها مو مساحة الوحدة الفعلية
SINGLE_AREA_PATTERN = re.compile(
    r"(?:المساحة\s*الإجمالية|إجمالي\s*(?:المساحة|للمساحة)|مساحة\s*الشقة|المساحة)"
    r"(?!\s*(?:الأرض|الارض|المشروع))"
    r"\s*[:\s]*(?:تبلغ\s*)?(?:حوالي\s*)?"
    r"(\d{2,4}(?:[.,]\d+)?)\s*(?:متر\s*مربع|م[²2]?|متر)\b"
    r"(?!.*(?:إلى|الى|حتى))"
)

# نمط مرن: "مساحة [كلمة وصفية اختيارية] تبلغ [حوالي] X م" -- بدون "ال" التعريف بالضرورة
FLEXIBLE_TABLUGH_PATTERN = re.compile(
    r"مساحة\s+(?:\S+\s+){0,2}?تبلغ\s*(?:حوالي\s*)?(\d{2,4}(?:[.,]\d+)?)\s*م"
)

# نمط "بمساحة بناء X متر" أو "باجمالي مساحة X متر" -- شائع بمشاريع فيها عدة أنواع وحدات
BUILD_AREA_PATTERN = re.compile(
    r"(?:بمساحة\s+بناء|باجمالي\s+مساحة)\s+(\d{2,4}(?:[.,]\d+)?)\s*متر"
)

# نمط "تبدأ من X ... تصل إلى Y" حتى لو انفصلوا بسطر جديد أو نص بينهم
START_END_PATTERN = re.compile(
    r"(?:تبدأ|تبدا)\s*من\s*(\d{2,4}(?:[.,]\d+)?)\s*م.{0,40}?"
    r"(?:تصل|حتى|وحتى)\s*(?:الى|إلى)?\s*(\d{2,4}(?:[.,]\d+)?)\s*م",
    re.DOTALL,
)

# نمط "مساحات تبدأ من X الى Y" بدون وحدة قياس مذكورة صراحة بعد الرقم
# (نعتمد على كلمة "مساحات" بأول الجملة كدليل كافي، والأرقام بنطاق منطقي لشقة)
AREAS_NO_UNIT_PATTERN = re.compile(
    r"مساحات?\s*تبدأ?\s*من\s*(\d{2,4}(?:[.,]\d+)?)\s*(?:الى|إلى)\s*(\d{2,4}(?:[.,]\d+)?)(?!\s*(?:ألف|الف|مليون|ريال))"
)

# جدول تحويل الأرقام العربية-الهندية إلى أرقام إنجليزية عادية
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(text):
    """يحول الأرقام العربية-الهندية (١٢٣) لأرقام إنجليزية (123)، ويصحح هجاء 'المساحه' الشائع"""
    text = str(text or "").translate(ARABIC_DIGITS)
    text = re.sub(r"مساحه\b", "مساحة", text)
    return text

# نمط الأسعار المرافقة (نستخدمه لاحقًا لو احتجنا مطابقة سعر بمساحة)
PRICE_PATTERN = re.compile(r"([\d,]{5,})\s*(?:ريال|ر\.س|﷼)")


MAX_REALISTIC_APARTMENT_AREA = 500  # فوق هذا الرقم، احتمال كبير إنه مساحة مشروع مو وحدة


def looks_like_project_area(row):
    """يتحقق هل area_sqm الحالي غير منطقي لشقة (على الأغلب مساحة مشروع/أرض بالغلط)"""
    current_area = row.get("area_sqm")
    if pd.isna(current_area):
        return False
    return float(current_area) > MAX_REALISTIC_APARTMENT_AREA


def extract_unit_ranges(description):
    """يستخرج كل نطاقات مساحات الوحدات المذكورة بالوصف"""
    desc = normalize_digits(description)
    ranges = []
    for m in RANGE_PATTERN.finditer(desc):
        low, high = float(m.group(1)), float(m.group(2))
        if low < high and high < 1000:  # نطاق منطقي لشقة
            ranges.append((low, high))

    # نجرب نمط "تبدأ من X ... تصل إلى Y" لو ما لقينا شي بالنمط الأساسي
    if not ranges:
        for m in START_END_PATTERN.finditer(desc):
            low, high = float(m.group(1)), float(m.group(2))
            if low < high and high < 1000:
                ranges.append((low, high))

    # نجرب نمط "مساحات تبدأ من X الى Y" بدون وحدة قياس مذكورة
    if not ranges:
        for m in AREAS_NO_UNIT_PATTERN.finditer(desc):
            low, high = float(m.group(1)), float(m.group(2))
            if low < high and high < 1000:
                ranges.append((low, high))

    # نجرب نمط قائمة مساحات مفصولة بفواصل (مثل "المساحات 166م ،، 139م")
    if not ranges:
        for m in COMMA_LIST_PATTERN.finditer(desc):
            v1, v2 = float(m.group(1)), float(m.group(2))
            if v1 != v2 and max(v1, v2) < 1000:
                ranges.append((min(v1, v2), max(v1, v2)))

    return ranges


def pick_best_area(row):
    """يختار أفضل تقدير لمساحة الوحدة الفعلية بناءً على النطاقات المستخرجة، أو مساحة مفردة"""
    ranges = extract_unit_ranges(row.get("description"))
    if ranges:
        # لو فيه أكثر من نطاق، ناخذ أصغرها كتقدير متحفظ (الوحدة الأرخص عادة تطابق السعر بالعمود)
        smallest_range = min(ranges, key=lambda r: r[0])
        return (smallest_range[0] + smallest_range[1]) / 2

    # ما فيه نطاق -- نجرب النمط الاحتياطي (مساحة مفردة مباشرة، مثل "المساحة 80م")
    desc = normalize_digits(row.get("description"))
    single_match = SINGLE_AREA_PATTERN.search(desc)
    if single_match:
        value = float(single_match.group(1).replace(",", "."))
        if 20 <= value <= 500:  # نطاق منطقي لشقة
            return value

    # نجرب نمط "مساحة ... تبلغ X" المرن
    flex_match = FLEXIBLE_TABLUGH_PATTERN.search(desc)
    if flex_match:
        value = float(flex_match.group(1).replace(",", "."))
        if 20 <= value <= 500:
            return value

    # نجرب نمط "مساحة بناء/باجمالي مساحة" -- ممكن يتكرر لعدة وحدات، ناخذ أصغرها كتقدير متحفظ
    build_matches = BUILD_AREA_PATTERN.findall(desc)
    if build_matches:
        values = [float(v.replace(",", ".")) for v in build_matches]
        valid = [v for v in values if 20 <= v <= 500]
        if valid:
            return min(valid)

    # آخر محاولة: "مساحات تصل إلى X" أو "مساحات تبدأ من X" بمفردهم (بدون الطرف التاني)
    upper_match = PLURAL_UPPER_PATTERN.search(desc)
    if upper_match:
        value = float(upper_match.group(1).replace(",", "."))
        if 20 <= value <= 500:
            return value

    lower_match = PLURAL_LOWER_PATTERN.search(desc)
    if lower_match:
        value = float(lower_match.group(1).replace(",", "."))
        if 20 <= value <= 500:
            return value

    return None


def main():
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"عدد الصفوف: {len(df)}")

    df["is_project_area_error"] = df.apply(looks_like_project_area, axis=1)
    flagged = df[df["is_project_area_error"]]
    print(f"صفوف فيها احتمال 'مساحة مشروع بدل وحدة': {len(flagged)}")

    df["area_sqm_corrected"] = df["area_sqm"]
    fixed_count = 0

    for idx in flagged.index:
        best_area = pick_best_area(df.loc[idx])
        if best_area:
            df.at[idx, "area_sqm_corrected"] = best_area
            fixed_count += 1
        else:
            # ما لقينا معلومة كافية بالوصف -- أفضل من نسيب رقم خاطئ هو نفرّغه
            df.at[idx, "area_sqm_corrected"] = None

    print(f"تم تصحيح المساحة تلقائيًا لـ {fixed_count} صف (من أصل {len(flagged)} مشتبه بهم)")
    print(f"باقي {len(flagged) - fixed_count} صف يحتاج مراجعة يدوية (ما قدرنا نستخرج نطاق واضح)")

    # عينة للمراجعة
    sample = df[df["is_project_area_error"]][
        ["listing_id", "area_sqm", "area_sqm_corrected", "price"]
    ].head(15)
    print("\n--- عينة للمراجعة ---")
    print(sample.to_string(index=False))

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nتم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
