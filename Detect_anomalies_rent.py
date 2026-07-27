"""
كشف الشذوذ ببيانات الإيجار باستخدام Isolation Forest
يقرأ data/listings_rent_clean.csv (الناتج النظيف من clean_rent_data.py)
يطلع ملفين: listings_rent_normal.csv و listings_rent_anomalies.csv
"""

import pandas as pd
from sklearn.ensemble import IsolationForest
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "listings_rent_clean.csv")

CONTAMINATION = 0.03  # النسبة المتوقعة من البيانات الشاذة (3% -- عدّلها حسب ما تشوف مناسب)


def main():
    if not os.path.exists(INPUT_PATH):
        print(f"تحذير: ما لقيت {INPUT_PATH} -- شغّل clean_rent_data.py أول")
        return

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"عدد الصفوف: {len(df)}")

    # نحسب سعر المتر كميزة إضافية تساعد بكشف الشذوذ المركّب
    df["price_per_sqm"] = df["price"] / df["area_sqm"]

    feature_cols = ["price", "area_sqm", "price_per_sqm", "rooms"]
    valid = df.dropna(subset=feature_cols).copy()
    print(f"صفوف صالحة للتحليل (بدون فراغات بالميزات): {len(valid)}")

    model = IsolationForest(contamination=CONTAMINATION, random_state=42, n_estimators=200)
    predictions = model.fit_predict(valid[feature_cols])
    valid["anomaly_score"] = model.decision_function(valid[feature_cols])
    valid["is_anomaly"] = predictions == -1

    anomalies = valid[valid["is_anomaly"]].sort_values("anomaly_score")
    normal = valid[~valid["is_anomaly"]]

    print(f"\nعدد الشاذ المكتشف: {len(anomalies)} ({len(anomalies)/len(valid)*100:.1f}%)")
    print(f"عدد الطبيعي: {len(normal)}")

    # تصنيف تلقائي لكل حالة شاذة -- بدون حاجة لمراجعة يدوية لكل صف
    global_median_psqm = normal["price_per_sqm"].median()
    district_median = normal.groupby("district")["price_per_sqm"].median()

    def classify_reason(row):
        psqm = row["price_per_sqm"]
        district = row["district"]
        d_median = district_median.get(district, global_median_psqm)
        ratio_to_district = psqm / d_median if d_median else None
        ratio_to_global = psqm / global_median_psqm
        rooms = row.get("rooms")
        area = row.get("area_sqm")
        area_per_room = area / rooms if rooms and rooms > 0 else None

        if ratio_to_district and ratio_to_district >= 3:
            return "سعر مرتفع جدًا عن متوسط الحي (فخامة على الأغلب)"
        if ratio_to_district and ratio_to_district <= 0.35:
            return "سعر منخفض جدًا عن متوسط الحي (فرصة محتملة)"
        if ratio_to_global >= 3:
            return "سعر مرتفع جدًا عن متوسط الرياض (فخامة على الأغلب)"
        if ratio_to_global <= 0.35:
            return "سعر منخفض جدًا عن متوسط الرياض (فرصة محتملة)"
        if area_per_room and area_per_room > 80:
            return "مساحة كبيرة مقابل الغرف (شقة فاخرة/تصميم غير معتاد)"
        if area_per_room and area_per_room < 15:
            return "مساحة صغيرة مقابل الغرف (تصميم غير معتاد)"
        if rooms and rooms >= 6:
            return "عدد غرف كبير (شبه فيلا/كمبوند)"
        return "شذوذ تركيبة عامة (مزيج عوامل)"

    anomalies = anomalies.copy()
    anomalies["السبب_المرجّح"] = anomalies.apply(classify_reason, axis=1)

    print("\n--- توزيع الأسباب المرجّحة (تلقائي) ---")
    print(anomalies["السبب_المرجّح"].value_counts().to_string())

    opportunities = anomalies[anomalies["السبب_المرجّح"].str.contains("فرصة محتملة")]
    print(f"\n🎯 فرص محتملة (سعر منخفض بشكل ملحوظ): {len(opportunities)}")

    print("\n--- أشد 10 حالات شذوذًا (الأكثر غرابة) ---")
    cols_to_show = ["listing_id", "district", "price", "area_sqm", "price_per_sqm", "rooms", "anomaly_score", "السبب_المرجّح"]
    print(anomalies[cols_to_show].head(10).to_string(index=False))

    anomalies_path = os.path.join(DATA_DIR, "listings_rent_anomalies.csv")
    normal_path = os.path.join(DATA_DIR, "listings_rent_normal.csv")

    anomalies.to_csv(anomalies_path, index=False, encoding="utf-8-sig")
    normal.to_csv(normal_path, index=False, encoding="utf-8-sig")

    print(f"\nتم الحفظ:")
    print(f"  الشاذ: {anomalies_path}")
    print(f"  الطبيعي: {normal_path}")
    print("\n✅ التصنيف تلقائي بالكامل -- ركّز مراجعتك على فئة 'فرصة محتملة' بس، الباقي فخامة/تصميم غير معتاد")


if __name__ == "__main__":
    main()
