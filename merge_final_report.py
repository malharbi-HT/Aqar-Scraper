"""
يدمج ناتج generate_investment_reports.py (تقدير العائد) مع ناتج
compare_sale_to_deals.py (مقارنة السعر بصفقات رسمية مشابهة) بملف نهائي واحد،
بعمودين منفصلين للتوصية عشان تشوف الاثنين مع بعض:

verdict_yield   -- التوصية المبنية على العائد المتوقع (Proceed/Review حسب نسبة الإيجار)
verdict_price   -- التوصية المبنية على مقارنة سعر البيع بصفقات رسمية مشابهة (🟢/🟡/🔴)
"""

import pandas as pd
import os
from official_district_data import OFFICIAL_RENT_PER_SQM

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INVESTMENT_REPORTS_PATH = os.path.join(DATA_DIR, "investment_reports.csv")
PRICE_VERIFICATION_PATH = os.path.join(DATA_DIR, "sale_price_verification.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "final_combined_report.csv")


def main():
    if not os.path.exists(INVESTMENT_REPORTS_PATH):
        print(f"تحذير: ما لقيت {INVESTMENT_REPORTS_PATH} -- شغّل generate_investment_reports.py أول")
        return
    if not os.path.exists(PRICE_VERIFICATION_PATH):
        print(f"تحذير: ما لقيت {PRICE_VERIFICATION_PATH} -- شغّل compare_sale_to_deals.py أول")
        return

    reports = pd.read_csv(INVESTMENT_REPORTS_PATH, encoding="utf-8-sig")
    verification = pd.read_csv(PRICE_VERIFICATION_PATH, encoding="utf-8-sig")
    print(f"عدد صفوف تقرير العائد: {len(reports)}")
    print(f"عدد صفوف مقارنة الصفقات: {len(verification)}")

    # نعيد تسمية أعمدة التوصية بكل ملف عشان توضح مصدرها بالجدول النهائي
    reports = reports.rename(columns={
        "verdict": "verdict_yield",
        "verdict_reason": "verdict_yield_reason",
    })

    verification_slim = verification[[
        "listing_id", "ad_price_per_sqm", "comparable_deals_count",
        "comparable_median_price_per_sqm", "ratio", "verdict", "reason",
    ]].rename(columns={
        "verdict": "verdict_price",
        "reason": "verdict_price_reason",
    })

    # دمج بمفتاح listing_id -- نستخدم left join عشان نحتفظ بكل عقارات تقرير العائد
    # حتى لو ما لقينا لها مقارنة صفقات رسمية (بيطلع verdict_price فاضي بهالحالة)
    merged = reports.merge(verification_slim, on="listing_id", how="left")

    matched_count = merged["verdict_price"].notna().sum()
    print(f"\nعدد العقارات اللي عندها الاثنين (عائد + مقارنة صفقات): {matched_count}")
    print(f"عدد العقارات اللي عندها تقدير عائد بس (بدون مقارنة صفقات): {len(merged) - matched_count}")

    # عمود يوضح هل الحي من ضمن الـ11 حي التجريبية (اللي عندنا بيانات رسمية موثقة لها)
    eleven_districts = set(OFFICIAL_RENT_PER_SQM.keys())
    merged["ضمن_الـ11_حي_التجريبية"] = merged["district"].isin(eleven_districts)

    cols_order = [
        "listing_id", "url", "title", "district", "direction",
        "ضمن_الـ11_حي_التجريبية",
        "price", "area_sqm", "rooms", "bathrooms", "livings", "age_years",
        "مؤثثة", "رقم_التواصل",
        "price_per_sqm", "rent_low", "rent_mid", "rent_high",
        "yield_low_pct", "yield_mid_pct", "yield_high_pct",
        "strengths", "risks",
        "verdict_yield", "verdict_yield_reason",
        "ad_price_per_sqm", "comparable_deals_count", "comparable_median_price_per_sqm", "ratio",
        "verdict_price", "verdict_price_reason",
        "description",
    ]
    cols_order = [c for c in cols_order if c in merged.columns]
    merged = merged[cols_order]

    merged.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nتم الحفظ: {OUTPUT_PATH}")

    print("\n--- توزيع العقارات: داخل/خارج الـ11 حي التجريبية ---")
    print(merged["ضمن_الـ11_حي_التجريبية"].value_counts().to_string())

    print("\n--- توزيع التوصيتين مع بعض ---")
    print(merged.groupby(["verdict_yield", "verdict_price"], dropna=False).size().to_string())


if __name__ == "__main__":
    main()
