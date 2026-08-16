"""
يقارن سعر كل إعلان بيع (من إعلاناتنا المسحوبة) بصفقات البيع الرسمية المشابهة
(نفس الحي + مساحة قريبة)، ويصنّف الفرق:

-- سعر رخيص جدًا مقارنة بصفقات مشابهة = مو فرصة تلقائية، غالبًا مؤشر مشكلة
   بالبيانات (فرق مساحة إعلان/صك، خطأ سعر...) -- يحتاج مراجعة يدوية قبل الشراء
-- سعر بنفس النطاق المعقول = سعر عادل، آمن نعتمد عليه
-- سعر أغلى بوضوح = مبالغ فيه، مو صفقة جيدة
"""

import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# غيّر هذي المسارات حسب أسماء ملفاتك الفعلية
ADS_PATH = os.path.join(DATA_DIR, "listings_sale_normal.csv")           # إعلاناتنا المسحوبة
DEALS_PATH = os.path.join(DATA_DIR, "sale_deals_riyadh_2025_2026.csv")  # صفقات وزارة العدل الرسمية

OUTPUT_PATH = os.path.join(DATA_DIR, "sale_price_verification.csv")

# نطاق المساحة المقبول للمقارنة (±25% من مساحة الإعلان)
AREA_TOLERANCE_PCT = 0.25

# حدود التصنيف (نسبة سعر متر الإعلان ÷ سعر متر الصفقات المشابهة)
SUSPICIOUS_LOW_RATIO = 0.60   # أرخص من 60% من السوق المشابه = مريب، يحتاج تحقق
FAIR_HIGH_RATIO = 1.15        # أغلى من 115% = مبالغ فيه

# أقل عدد صفقات مشابهة نحتاجه عشان نثق بالمقارنة
MIN_COMPARABLE_DEALS = 3


def find_comparable_deals(deals_district, ad_area):
    """يرجع الصفقات اللي مساحتها قريبة من مساحة الإعلان (±25%)، ونوعها شقة بس"""
    area_col = "المساحة (متر مربع)"
    type_col = "النوع"  # ⚠️ تأكد هذا الاسم مطابق بالضبط لعمود نوع العقار بملفك

    low = ad_area * (1 - AREA_TOLERANCE_PCT)
    high = ad_area * (1 + AREA_TOLERANCE_PCT)
    comparable = deals_district[(deals_district[area_col] >= low) & (deals_district[area_col] <= high)]

    if type_col in comparable.columns:
        comparable = comparable[comparable[type_col].astype(str).str.contains("شق", na=False)]

    return comparable


def classify(ratio):
    if ratio < SUSPICIOUS_LOW_RATIO:
        return "🔴 REVIEW", f"سعر المتر أرخص بشكل غير طبيعي ({ratio:.0%} من صفقات مشابهة) -- تحقق من المساحة والصك قبل أي التزام"
    elif ratio > FAIR_HIGH_RATIO:
        return "🟡 مبالغ فيه", f"سعر المتر أعلى من صفقات مشابهة ({ratio:.0%}) -- سعر غير تنافسي"
    else:
        return "🟢 سعر عادل", f"سعر المتر ضمن نطاق صفقات مشابهة ({ratio:.0%})"


def main():
    if not os.path.exists(ADS_PATH) or not os.path.exists(DEALS_PATH):
        print("تحذير: تأكد من وجود ملفي الإعلانات والصفقات الرسمية بالمسارات المحددة بأول السكربت")
        return

    ads = pd.read_csv(ADS_PATH, encoding="utf-8-sig")
    deals = pd.read_csv(DEALS_PATH, encoding="utf-8-sig")
    print(f"عدد الإعلانات: {len(ads)}")
    print(f"عدد الصفقات الرسمية: {len(deals)}")

    # نطابق اسم الحي: نشيل "حي " من إعلاناتنا عشان تطابق تسمية ملف الصفقات
    ads = ads.copy()
    ads["حي_مطابق"] = ads["district"].str.replace("حي ", "", regex=False).str.strip()

    results = []
    for _, ad in ads.iterrows():
        district = ad["حي_مطابق"]
        deals_district = deals[deals["الحي"] == district]
        if len(deals_district) == 0:
            continue  # ما عندنا صفقات لهالحي، نتخطاه

        comparable = find_comparable_deals(deals_district, ad["area_sqm"])
        if len(comparable) < MIN_COMPARABLE_DEALS:
            continue  # عينة قليلة جدًا، ما نثق بالمقارنة

        ad_price_per_sqm = ad["price"] / ad["area_sqm"]
        comparable_median_price_per_sqm = comparable["سعر المتر المربع (ريال)"].median()
        ratio = ad_price_per_sqm / comparable_median_price_per_sqm

        verdict, reason = classify(ratio)

        results.append({
            "listing_id": ad["listing_id"],
            "url": ad["url"],
            "district": ad["district"],
            "price": ad["price"],
            "area_sqm": ad["area_sqm"],
            "ad_price_per_sqm": round(ad_price_per_sqm),
            "comparable_deals_count": len(comparable),
            "comparable_median_price_per_sqm": round(comparable_median_price_per_sqm),
            "ratio": round(ratio, 2),
            "verdict": verdict,
            "reason": reason,
        })

    result_df = pd.DataFrame(results).sort_values("ratio")
    print(f"\nعدد الإعلانات القابلة للمقارنة (لها صفقات مشابهة كافية): {len(result_df)}")
    print("\n--- توزيع التصنيف ---")
    print(result_df["verdict"].value_counts().to_string())

    result_df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nتم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
