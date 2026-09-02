"""
فلترة سريعة بدون أي API -- يلقط كل إعلان يذكر كلمات تأجير بالوصف (Regex بس،
صفر توكن، صفر تكلفة). هذا الملف يعطيك القائمة الكاملة الخام، بدون تحقق أو
استخراج دقيق للإيجار (هذا يحتاج LLM بملف hissatech_analyzer.py).

الفرق عن الملف النهائي (currently_rented_properties.csv):
- هذا: كل إعلان يذكر كلمة تأجير، بدون تأكيد فعلي ولا رقم إيجار دقيق
- الآخر: بعد تحقق LLM، مؤكد إنه مؤجّر فعليًا + رقم إيجار مستخرج بدقة
"""

import pandas as pd
import os
import re

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "listings_sale_normal.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "rented_candidates_no_api.csv")

RENTED_HINTS = re.compile(
    r"مؤجرة|مؤجر\b|مؤجّرة|مؤجّر\b|"
    r"يوجد مستأجر|مستأجر حاليًا|مستأجر حاليا|"
    r"عقد إيجار ساري|عقد ايجار ساري|"
    r"عقد إيجار سنوي|عقد ايجار سنوي|"
    r"دخل ثابت|مؤجرة سنوي|مؤجر سنوي",
    re.IGNORECASE,
)


def main():
    if not os.path.exists(INPUT_PATH):
        print(f"تحذير: ما لقيت {INPUT_PATH}")
        return

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"إجمالي الإعلانات: {len(df)}")

    mask = df["description"].fillna("").astype(str).str.contains(RENTED_HINTS, na=False)
    candidates = df[mask].copy()
    print(f"إعلانات تذكر تأجير (بدون تحقق، Regex بس): {len(candidates)}")

    # نرتّب حسب السعر تنازليًا بس عشان يكون فيه ترتيب منطقي، ما فيه رقم إيجار مؤكد بعد
    cols = [c for c in ["listing_id", "url", "title", "district", "direction",
                          "price", "area_sqm", "rooms", "bathrooms", "age_years",
                          "description"] if c in candidates.columns]
    candidates = candidates[cols]

    candidates.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
