"""
فحص إضافي أخير: يقارن مساحة كل عقار (العمود) مع أي مساحة مذكورة بنص الوصف،
بدون قيد "فوق 500م²" (خلاف fix_area_nlp.py الأساسي). يلقط حالات زي:
"المساحة 350م²" بالوصف بينما العمود مسجّل 262م" -- فرق حقيقي تحت حد الاشتباه الأول.
"""

import pandas as pd
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from fix_area_nlp import extract_unit_ranges, SINGLE_AREA_PATTERN, normalize_digits

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "listings_sale_price_fixed.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "listings_sale_area_crosschecked.csv")

# لو الفرق بين المساحة المذكورة بالوصف والعمود أكبر من هذي النسبة، نعتبره خطأ
MISMATCH_RATIO_LOW = 0.75
MISMATCH_RATIO_HIGH = 1.35

# لو النطاق المذكور بالوصف واسع جدًا (فرق كبير بين أصغر وأكبر رقم)، يبين إنه
# نطاق مشروع كامل بعدة أنواع وحدات، مو مساحة وحدة واحدة محددة -- نتجاهله بدل ما نصحح بغلط
MAX_RELIABLE_RANGE_SPREAD = 60


def extract_area_from_description(description):
    """يحاول يستخرج مساحة وحيدة (رقم مفرد، مو نطاق) من الوصف للمقارنة المباشرة"""
    ranges = extract_unit_ranges(description)
    # نستبعد النطاقات الواسعة جدًا (مشروع بعدة أنواع وحدات، مو وحدة واحدة موثوقة)
    reliable_ranges = [r for r in ranges if (r[1] - r[0]) <= MAX_RELIABLE_RANGE_SPREAD]
    if reliable_ranges:
        smallest = min(reliable_ranges, key=lambda r: r[0])
        return (smallest[0] + smallest[1]) / 2

    desc = normalize_digits(description)
    m = SINGLE_AREA_PATTERN.search(desc)
    if m:
        value = float(m.group(1).replace(",", "."))
        if 20 <= value <= 1000:
            return value

    return None


def main():
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")

    # ندمج السعر المصحح لو موجود (استمرارية مع الخطوة السابقة)
    if "price_corrected" in df.columns:
        still_wrong = df.get("is_price_error", False) & df["price_corrected"].isna()
        df = df[~still_wrong].copy()
        df["price"] = df["price_corrected"].fillna(df["price"])
        df = df.drop(columns=["price_corrected", "is_price_error"], errors="ignore")

    print(f"عدد الصفوف: {len(df)}")

    print("نستخرج المساحة من وصف كل صف للمقارنة (يستغرق شوي)...")
    df["_desc_area"] = df["description"].apply(extract_area_from_description)

    def is_mismatch(row):
        desc_area = row["_desc_area"]
        col_area = row["area_sqm"]
        if pd.isna(desc_area) or pd.isna(col_area) or col_area == 0:
            return False
        ratio = col_area / desc_area
        return ratio < MISMATCH_RATIO_LOW or ratio > MISMATCH_RATIO_HIGH

    df["is_area_mismatch"] = df.apply(is_mismatch, axis=1)
    flagged = df[df["is_area_mismatch"]]
    print(f"صفوف فيها فرق حقيقي بين المساحة بالعمود والوصف: {len(flagged)}")

    df["area_sqm_final"] = df["area_sqm"]
    df.loc[df["is_area_mismatch"], "area_sqm_final"] = df.loc[df["is_area_mismatch"], "_desc_area"]

    df = df.drop(columns=["_desc_area"])

    sample = df[df["is_area_mismatch"]][["listing_id", "area_sqm", "area_sqm_final", "price"]].head(20)
    print("\n--- عينة للمراجعة ---")
    print(sample.to_string(index=False))

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nتم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
