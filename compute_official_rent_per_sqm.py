"""
يحسب سعر متر الإيجار السنوي الرسمي (وسيط) لكل حي، من ملف بيانات إيجار الخام
(عقود موثّقة فعليًا من منصة إيجار). يطلع جدول جاهز + قاموس بايثون تقدر تنسخه
مباشرة لملف official_district_data.py.

المدخل المتوقع: ملف CSV فيه أعمدة (على الأقل): الحي، سعر المتر (ريال)،
الإيجار السنوي (ريال)، المساحة (م²)
"""

import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# غيّر اسم الملف هنا لو مختلف عندك
INPUT_PATH = os.path.join(DATA_DIR, "ejar_rent_data_11_districts.csv")

# أي مساحة أقل من هذا نعتبرها خطأ إدخال (مستحيل شقة سكنية بهالحجم)
MIN_REALISTIC_AREA = 20


def main():
    if not os.path.exists(INPUT_PATH):
        print(f"تحذير: ما لقيت {INPUT_PATH}")
        print("ارفع ملف بيانات الإيجار الخام لمجلد data/ بنفس هذا الاسم، أو عدّل INPUT_PATH")
        return

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"عدد الصفوف الكلي: {len(df)}")

    area_col = "المساحة (م²)"
    rent_col = "الإيجار السنوي (ريال)"
    price_per_sqm_col = "سعر المتر (ريال)"
    district_col = "الحي"

    before = len(df)
    clean = df[df[area_col] >= MIN_REALISTIC_AREA].copy()
    print(f"استبعدنا {before - len(clean)} صف بمساحة غير واقعية (أقل من {MIN_REALISTIC_AREA}م²)")

    result = clean.groupby(district_col).agg(
        عدد_العقود=(price_per_sqm_col, "count"),
        سعر_المتر_الوسيط=(price_per_sqm_col, "median"),
        متوسط_المساحة=(area_col, "median"),
        متوسط_الإيجار=(rent_col, "median"),
    ).round(0)

    result = result.sort_values("سعر_المتر_الوسيط", ascending=False)

    print("\n--- الجدول الكامل ---")
    print(result.to_string())

    # نطبع القاموس جاهز بصيغة بايثون -- تنسخه مباشرة لملف official_district_data.py
    print("\n--- جاهز للنسخ لملف official_district_data.py ---")
    print("OFFICIAL_RENT_PER_SQM = {")
    for district, row in result.iterrows():
        district_name = district if district.startswith("حي") else f"حي {district}"
        print(f'    "{district_name}": {int(row["سعر_المتر_الوسيط"])},')
    print("}")

    out_path = os.path.join(DATA_DIR, "official_rent_per_sqm_computed.csv")
    result.to_csv(out_path, encoding="utf-8-sig")
    print(f"\nتم حفظ الجدول الكامل: {out_path}")


if __name__ == "__main__":
    main()
