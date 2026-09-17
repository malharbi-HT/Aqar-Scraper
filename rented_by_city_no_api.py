"""
يطبّق نفس بايبلاين التنظيف واستخراج المؤجّرة (اللي بنيناه للرياض) على بيانات
مدينة ثانية (المدينة المنورة أو جدة) -- بدون أي API، Regex بحت.

الفرق عن الرياض: بيانات المدينة/جدة مدمجة أصلاً بملف واحد لكل الأنواع (عمود
"property_type" موجود جاهز من السحب نفسه)، عكس الرياض اللي كانت ملفات
منفصلة لكل نوع. فبدل 3 سكربتات منفصلة (شقق/أنواع ثانية/من المالك)، هذا
سكربت واحد شامل يطبّق كل المراحل الثلاث دفعة وحدة، وينتج ملف نهائي واحد
فيه عمود "من_المالك_مباشرة" يوضح أي عقار يوافق الشرط.

الاستخدام: python rented_by_city_no_api.py medina
           python rented_by_city_no_api.py jeddah
"""

import pandas as pd
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from rented_extracted_no_api import (
    RENTED_HINTS, extract_annual_rent, sanity_check_rent,
    extract_key_features, normalize_for_duplicate_check,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# صياغات شائعة تدل على إعلان مباشر من المالك بنص الوصف (نفس منطق ملف الرياض)
OWNER_HINTS = re.compile(
    r"من\s*المالك\s*مباشرة?|مباشر(?:ة)?\s*من\s*المالك|أنا\s*المالك|"
    r"من\s*صاحب\s*العقار|المالك\s*مباشرة?|بدون\s*وسيط|بدون\s*وسطاء|"
    r"مباشرة?\s*من\s*صاحب|والمالك\s*(?:سمح|موافق)",
    re.IGNORECASE,
)


def is_owner_direct(row):
    description = str(row.get("description", ""))
    if OWNER_HINTS.search(description):
        return True, "الوصف يذكر إعلان مباشر من المالك"

    company = row.get("advertiser_company")
    adv_type = row.get("advertiser_type")

    if pd.notna(adv_type) and adv_type == 0:
        return True, "advertiser_type = 0 (بدون شركة مسجّلة)"

    if pd.isna(company) or str(company).strip() == "":
        if "advertiser_company" in row.index:
            return True, "عمود الشركة فاضي (فرد)"

    return False, ""


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("medina", "jeddah"):
        print("الاستخدام: python rented_by_city_no_api.py medina|jeddah")
        return
    city_key = sys.argv[1]
    city_label = "المدينة المنورة" if city_key == "medina" else "جدة"

    normal_path = os.path.join(DATA_DIR, f"listings_sale_{city_key}_all_types_normal.csv")
    raw_path = os.path.join(DATA_DIR, f"listings_sale_{city_key}_all_types.csv")
    input_path = normal_path if os.path.exists(normal_path) else raw_path
    print(f"نقرأ من: {input_path}" + (" (نسخة نظيفة بعد كشف الشذوذ)" if input_path == normal_path else " (الخام -- كشف الشذوذ ما اشتغل بعد)"))
    output_path = os.path.join(DATA_DIR, f"rented_{city_key}_no_api.csv")

    if not os.path.exists(input_path):
        print(f"تحذير: ما لقينا {input_path}")
        return

    df = pd.read_csv(input_path, encoding="utf-8-sig")
    print(f"{city_label}: إجمالي الإعلانات: {len(df)}")

    # المرحلة 1: فلترة مؤجّرة
    mask = df["description"].fillna("").astype(str).str.contains(RENTED_HINTS, na=False)
    candidates = df[mask].copy()
    print(f"مرشّحين (يذكرون تأجير): {len(candidates)}")

    if len(candidates) == 0:
        print("ما لقينا أي عقار مؤجّر -- توقف هنا")
        return

    # المرحلة 2: استخراج الإيجار والعائد (نفس منطق الرياض المُختبر)
    rents = []
    for _, row in candidates.iterrows():
        rent, _ = extract_annual_rent(row.get("description"), row.get("price"))
        rent = sanity_check_rent(rent, row.get("price"))
        rents.append(rent)
    candidates["actual_annual_rent"] = rents
    candidates["yield_pct"] = candidates.apply(
        lambda r: round(r["actual_annual_rent"] / r["price"] * 100, 2)
        if pd.notna(r["actual_annual_rent"]) and r.get("price") else None,
        axis=1
    )

    with_rent = candidates["actual_annual_rent"].notna().sum()
    print(f"لقينا رقم إيجار موثوق: {with_rent} من {len(candidates)}")

    # المرحلة 3: استخراج الخصائص
    candidates["key_features"] = candidates["description"].apply(extract_key_features)

    # المرحلة 4: كشف "من المالك مباشرة"
    owner_flags, owner_reasons = [], []
    for _, row in candidates.iterrows():
        is_owner, reason = is_owner_direct(row)
        owner_flags.append("نعم" if is_owner else "لا")
        owner_reasons.append(reason)
    candidates["من_المالك_مباشرة"] = owner_flags
    candidates["owner_detection_reason"] = owner_reasons

    owner_count = sum(1 for f in owner_flags if f == "نعم")
    print(f"من المالك مباشرة: {owner_count} من {len(candidates)}")

    # المرحلة 5: حذف التكرار
    candidates["_normalized_desc"] = candidates["description"].apply(normalize_for_duplicate_check)
    before_dedup = len(candidates)
    candidates = candidates.drop_duplicates(subset="_normalized_desc", keep="first")
    candidates = candidates.drop(columns=["_normalized_desc"])
    print(f"حذفنا {before_dedup - len(candidates)} إعلان مكرر")

    # المرحلة 6: الترتيب -- عائد أول تنازليًا، بعدين الأجدد عمرًا
    candidates["_has_yield"] = candidates["yield_pct"].notna()
    candidates = candidates.sort_values(
        ["_has_yield", "yield_pct", "age_years"],
        ascending=[False, False, True],
        na_position="last"
    ).drop(columns=["_has_yield"])

    cols = [c for c in ["listing_id", "url", "title", "published_at", "property_type",
                          "district", "direction", "price", "area_sqm", "rooms",
                          "bathrooms", "age_years", "actual_annual_rent", "yield_pct",
                          "key_features", "من_المالك_مباشرة", "owner_detection_reason",
                          "advertiser_name", "description"] if c in candidates.columns]
    candidates = candidates[cols]

    # المرحلة 7: تنسيق الفواصل والنسبة المئوية
    for col in ["price", "actual_annual_rent"]:
        if col in candidates.columns:
            candidates[col] = candidates[col].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else v)
    if "yield_pct" in candidates.columns:
        candidates["yield_pct"] = candidates["yield_pct"].apply(lambda v: f"{v:.2f}%" if pd.notna(v) else v)

    candidates.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {output_path}")


if __name__ == "__main__":
    main()
