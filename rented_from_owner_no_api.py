"""
استخراج العقارات المؤجّرة من المالك مباشرة (بدون وسيط/شركة عقارية) --
Regex بحت، بدون أي API.

يعتمد على إشارتين (أيّ وحدة كافية):
1. الوصف نفسه يذكر "من المالك مباشرة" أو مشابه
2. عمود advertiser_company فاضي / advertiser_type = 0 (مفيش شركة مسجّلة
   للمعلن -- تأكدنا إحصائيًا إنه مرتبط 100% بغياب اسم الشركة)

يستخدم نفس دوال استخراج الإيجار المُختبرة من rented_extracted_no_api.py.
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
# نفضّل الملف المنظّف (normal)، ولو ما فيه أعمدة المعلن نرجع للملف الخام
INPUT_CANDIDATES = ["listings_sale_normal.csv", "listings_sale.csv"]
OUTPUT_PATH = os.path.join(DATA_DIR, "rented_from_owner_no_api.csv")

# صياغات شائعة تدل على إعلان مباشر من المالك بنص الوصف
OWNER_HINTS = re.compile(
    r"من\s*المالك\s*مباشرة?|مباشر(?:ة)?\s*من\s*المالك|أنا\s*المالك|"
    r"من\s*صاحب\s*العقار|المالك\s*مباشرة?|بدون\s*وسيط|بدون\s*وسطاء|"
    r"مباشرة?\s*من\s*صاحب|والمالك\s*(?:سمح|موافق)",
    re.IGNORECASE,
)


def load_input():
    for fname in INPUT_CANDIDATES:
        path = os.path.join(DATA_DIR, fname)
        if os.path.exists(path):
            df = pd.read_csv(path, encoding="utf-8-sig")
            return df, path
    return None, None


def is_owner_direct(row):
    """يتحقق من الإشارتين: نص الوصف، أو غياب شركة بعمود المعلن"""
    description = str(row.get("description", ""))
    if OWNER_HINTS.search(description):
        return True, "الوصف يذكر إعلان مباشر من المالك"

    # الإشارة الثانية: عمود المعلن (لو متوفر بالملف)
    company = row.get("advertiser_company")
    adv_type = row.get("advertiser_type")

    if pd.notna(adv_type) and adv_type == 0:
        return True, "advertiser_type = 0 (بدون شركة مسجّلة)"

    if pd.isna(company) or str(company).strip() == "":
        if "advertiser_company" in row.index:  # العمود موجود فعليًا، بس فاضي
            return True, "عمود الشركة فاضي (فرد)"

    return False, ""


def main():
    df, path = load_input()
    if df is None:
        print("تحذير: ما لقينا listings_sale_normal.csv ولا listings_sale.csv")
        return

    print(f"قرأنا من: {path} ({len(df)} إعلان)")
    has_advertiser_cols = "advertiser_company" in df.columns or "advertiser_type" in df.columns
    print(f"أعمدة المعلن متوفرة؟ {'نعم' if has_advertiser_cols else 'لا -- الاعتماد على نص الوصف بس'}")

    # المرحلة 1: فلترة مؤجّرة (نفس فلتر الشقق)
    rented_mask = df["description"].fillna("").astype(str).str.contains(RENTED_HINTS, na=False)
    rented = df[rented_mask].copy()
    print(f"مرشّحين مؤجّرة: {len(rented)}")

    # المرحلة 2: فلترة من المالك مباشرة (إشارتين)
    owner_flags, owner_reasons = [], []
    for _, row in rented.iterrows():
        is_owner, reason = is_owner_direct(row)
        owner_flags.append(is_owner)
        owner_reasons.append(reason)
    rented["_is_owner"] = owner_flags
    rented["owner_detection_reason"] = owner_reasons

    candidates = rented[rented["_is_owner"]].copy()
    print(f"مؤجّرة + من المالك مباشرة: {len(candidates)}")

    if len(candidates) == 0:
        print("ما لقينا أي عقار يطابق الشرطين -- توقف هنا")
        return

    # المرحلة 3: استخراج الإيجار والخصائص (نفس المنطق المُختبر)
    rents, reasons = [], []
    for _, row in candidates.iterrows():
        rent, reason = extract_annual_rent(row.get("description"), row.get("price"))
        rent = sanity_check_rent(rent, row.get("price"))
        rents.append(rent)
        reasons.append(reason)

    candidates["actual_annual_rent"] = rents
    candidates["yield_pct"] = candidates.apply(
        lambda r: round(r["actual_annual_rent"] / r["price"] * 100, 2)
        if pd.notna(r["actual_annual_rent"]) and r.get("price") else None,
        axis=1
    )
    candidates["key_features"] = candidates["description"].apply(extract_key_features)

    # حذف التكرار
    candidates["_normalized_desc"] = candidates["description"].apply(normalize_for_duplicate_check)
    before_dedup = len(candidates)
    candidates = candidates.drop_duplicates(subset="_normalized_desc", keep="first")
    candidates = candidates.drop(columns=["_normalized_desc"])
    print(f"حذفنا {before_dedup - len(candidates)} إعلان مكرر")

    # الترتيب: عائد أول تنازليًا، بعدين الأجدد عمرًا
    candidates["_has_yield"] = candidates["yield_pct"].notna()
    candidates = candidates.sort_values(
        ["_has_yield", "yield_pct", "age_years"],
        ascending=[False, False, True],
        na_position="last"
    ).drop(columns=["_has_yield", "_is_owner"])

    cols = [c for c in ["listing_id", "url", "title", "published_at", "district", "direction", "price",
                          "area_sqm", "rooms", "bathrooms", "age_years",
                          "actual_annual_rent", "yield_pct", "key_features",
                          "owner_detection_reason", "advertiser_name",
                          "description"] if c in candidates.columns]
    candidates = candidates[cols]

    for col in ["price", "actual_annual_rent"]:
        if col in candidates.columns:
            candidates[col] = candidates[col].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else v)
    if "yield_pct" in candidates.columns:
        candidates["yield_pct"] = candidates["yield_pct"].apply(lambda v: f"{v:.2f}%" if pd.notna(v) else v)

    candidates.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
