"""
يبني تقرير تحليل استثماري تفصيلي لكل عقار بقائمة الفرص -- سعر المتر، نطاق إيجار
(متشائم/متوسط/متفائل من توزيع أشجار النموذج)، عائد إجمالي وصافي بعدة سيناريوهات،
نقاط قوة/مخاطر مستخرجة من الوصف، وتوصية نهائية.
"""

import pandas as pd
import numpy as np
import re
import os
import joblib

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OPPORTUNITIES_PATH = os.path.join(DATA_DIR, "top_investment_opportunities.csv")
SALE_NORMAL_PATH = os.path.join(DATA_DIR, "listings_sale_normal.csv")
MODEL_PATH = os.path.join(DATA_DIR, "rent_model.joblib")
DISTRICT_ENCODING_PATH = os.path.join(DATA_DIR, "rent_model_district_encoding.joblib")

OUTPUT_PATH = os.path.join(DATA_DIR, "investment_reports.csv")

FURNISHED_PATTERN = re.compile(r"مفروش|مؤثث")
FEATURE_COLS = ["area_sqm", "rooms", "bathrooms", "livings", "age_years",
                "latitude", "longitude", "district_encoded", "is_furnished"]

# نسبة مصاريف تشغيل تقديرية (اتحاد ملاك + صيانة + شغور + عمولة تأجير) -- قابلة للتعديل
OPERATING_EXPENSE_PCT = 0.16

# كلمات تدل على مزايا إيجابية (نقاط قوة) -- نفحص وجودها بالوصف
STRENGTH_KEYWORDS = {
    "مصعد": "يوجد مصعد",
    "موقف": "يوجد موقف سيارة",
    "مترو": "قريب من محطة مترو",
    "دائري": "قريب من طريق دائري رئيسي",
    "خزان": "خزانات مياه مستقلة",
    "تشطيب": "تشطيبات حديثة مذكورة",
    "جديد": "عقار جديد",
}

# كلمات/أنماط تدل على مخاطر يستاهل الانتباه لها
RISK_PATTERNS = {
    r"يبدأ من|تبدأ من": "السعر 'يبدأ من' -- تأكد إنه يخص نفس الوحدة والمساحة المذكورة، مو وحدة أصغر",
    r"للتفاوض|قابل للتفاوض": "السعر قابل للتفاوض -- ممكن فيه هامش تفاوض إضافي",
}


def compute_rent_range(model, X_row):
    """يستخدم توزيع تنبؤات كل شجرة بالنموذج عشان يطلع نطاق (10%-50%-90%) بدل رقم واحد"""
    X_values = X_row.values  # نحول لمصفوفة نمباي -- يتفادى تحذير أسماء الأعمدة بالأشجار الفردية
    tree_predictions = np.array([tree.predict(X_values)[0] for tree in model.estimators_])
    low = np.percentile(tree_predictions, 10)
    mid = np.percentile(tree_predictions, 50)
    high = np.percentile(tree_predictions, 90)
    return low, mid, high


def extract_strengths(description):
    desc = str(description or "")
    return [label for keyword, label in STRENGTH_KEYWORDS.items() if keyword in desc]


def extract_risks(title, description):
    text = f"{title} {description}"
    return [label for pattern, label in RISK_PATTERNS.items() if re.search(pattern, text)]


def classify_verdict(net_yield_low):
    """التوصية النهائية مبنية على أسوأ سيناريو (الحد الأدنى)، مو أفضل حالة -- تحفّظ أكثر"""
    if net_yield_low >= 8:
        return "🟢 Proceed", "العائد الصافي حتى بأسوأ سيناريو فوق 8% -- فرصة قوية"
    elif net_yield_low >= 5:
        return "🟡 Proceed مشروط", "العائد الصافي معقول لكن يعتمد على افتراضات الإيجار -- راجع يدويًا"
    else:
        return "🔴 مراجعة دقيقة", "العائد الصافي بأسوأ سيناريو ضعيف -- تأكد من الأرقام قبل أي قرار"


def main():
    if not os.path.exists(OPPORTUNITIES_PATH):
        print(f"تحذير: ما لقيت {OPPORTUNITIES_PATH} -- شغّل apply_yield_model.py أول")
        return

    model = joblib.load(MODEL_PATH)
    district_encoding = joblib.load(DISTRICT_ENCODING_PATH)
    global_median_rent = district_encoding.median()

    opportunities = pd.read_csv(OPPORTUNITIES_PATH, encoding="utf-8-sig")
    sale_full = pd.read_csv(SALE_NORMAL_PATH, encoding="utf-8-sig")
    # نحتاج الوصف والعنوان الأصليين (مو موجودين بملف الفرص المختصر)
    sale_full = sale_full.set_index("listing_id")

    reports = []
    for _, row in opportunities.iterrows():
        listing_id = row["listing_id"]
        if listing_id not in sale_full.index:
            continue
        full_row = sale_full.loc[listing_id]

        price_per_sqm = round(row["price"] / row["area_sqm"], 0)

        is_furnished = int(bool(FURNISHED_PATTERN.search(str(full_row.get("description", "")))))
        district_val = district_encoding.get(full_row.get("district"), global_median_rent)

        X_row = pd.DataFrame([{
            "area_sqm": row["area_sqm"], "rooms": row["rooms"],
            "bathrooms": full_row.get("bathrooms"), "livings": full_row.get("livings"),
            "age_years": row.get("age_years"), "latitude": full_row.get("latitude"),
            "longitude": full_row.get("longitude"), "district_encoded": district_val,
            "is_furnished": is_furnished,
        }])[FEATURE_COLS]

        if X_row.isna().any(axis=None):
            continue  # نتخطى لو فيه نقص بخصائص أساسية للنطاق

        rent_low, rent_mid, rent_high = compute_rent_range(model, X_row)

        yield_low = round(rent_low / row["price"] * 100, 2)
        yield_mid = round(rent_mid / row["price"] * 100, 2)
        yield_high = round(rent_high / row["price"] * 100, 2)

        net_rent_low = rent_low * (1 - OPERATING_EXPENSE_PCT)
        net_yield_low = round(net_rent_low / row["price"] * 100, 2)

        strengths = extract_strengths(full_row.get("description"))
        risks = extract_risks(full_row.get("title"), full_row.get("description"))

        verdict, verdict_reason = classify_verdict(net_yield_low)

        reports.append({
            "listing_id": listing_id,
            "url": row["url"],
            "district": row["district"],
            "price": row["price"],
            "area_sqm": row["area_sqm"],
            "price_per_sqm": price_per_sqm,
            "rent_low": round(rent_low), "rent_mid": round(rent_mid), "rent_high": round(rent_high),
            "yield_low_pct": yield_low, "yield_mid_pct": yield_mid, "yield_high_pct": yield_high,
            "net_yield_low_pct": net_yield_low,
            "strengths": " | ".join(strengths),
            "risks": " | ".join(risks),
            "verdict": verdict,
            "verdict_reason": verdict_reason,
        })

    report_df = pd.DataFrame(reports).sort_values("net_yield_low_pct", ascending=False)
    report_df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print(f"عدد التقارير المبنية: {len(report_df)}")
    print(f"\n--- توزيع التوصيات ---")
    print(report_df["verdict"].value_counts().to_string())
    print(f"\nتم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
