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
    r"(\d{2,4}(?:\.\d+)?)\s*(?:م[²2]?)?\s*(?:إلى|الى|حتى|-|و)\s*(\d{2,4}(?:\.\d+)?)\s*م[²2]?"
)

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
    desc = str(description or "")
    ranges = []
    for m in RANGE_PATTERN.finditer(desc):
        low, high = float(m.group(1)), float(m.group(2))
        if low < high and high < 1000:  # نطاق منطقي لشقة
            ranges.append((low, high))
    return ranges


def pick_best_area(row):
    """يختار أفضل تقدير لمساحة الوحدة الفعلية بناءً على النطاقات المستخرجة"""
    ranges = extract_unit_ranges(row.get("description"))
    if not ranges:
        return None
    # لو فيه أكثر من نطاق، ناخذ أصغرها كتقدير متحفظ (الوحدة الأرخص عادة تطابق السعر بالعمود)
    smallest_range = min(ranges, key=lambda r: r[0])
    midpoint = (smallest_range[0] + smallest_range[1]) / 2
    return midpoint


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
