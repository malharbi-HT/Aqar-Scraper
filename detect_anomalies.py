"""
كشف الشذوذ ببيانات البيع باستخدام Isolation Forest
يقرأ data/listings_sale.csv (أو listings_sale_clean.csv لو موجود)
يطلع ملفين: listings_sale_normal.csv و listings_sale_anomalies.csv
"""

import pandas as pd
from sklearn.ensemble import IsolationForest
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# نستخدم النسخة النظيفة لو موجودة (بعد الحدود اليدوية)، وإلا الخام
CLEAN_PATH = os.path.join(DATA_DIR, "listings_sale_clean.csv")
RAW_PATH = os.path.join(DATA_DIR, "listings_sale.csv")

CONTAMINATION = 0.03  # النسبة المتوقعة من البيانات الشاذة (3% -- عدّلها حسب ما تشوف مناسب)


def main():
    input_path = CLEAN_PATH if os.path.exists(CLEAN_PATH) else RAW_PATH
    print(f"نقرأ من: {input_path}")

    df = pd.read_csv(input_path, encoding="utf-8-sig")
    print(f"عدد الصفوف: {len(df)}")

    # نحسب سعر المتر كميزة إضافية تساعد بكشف الشذوذ المركّب
    df["price_per_sqm"] = df["price"] / df["area_sqm"]

    feature_cols = ["price", "area_sqm", "price_per_sqm", "rooms"]
    # نشتغل بس على الصفوف اللي فيها كل الميزات (بدون فراغات)
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

    print("\n--- أشد 10 حالات شذوذًا (الأكثر غرابة) ---")
    cols_to_show = ["listing_id", "district", "price", "area_sqm", "price_per_sqm", "rooms", "anomaly_score"]
    print(anomalies[cols_to_show].head(10).to_string(index=False))

    anomalies_path = os.path.join(DATA_DIR, "listings_sale_anomalies.csv")
    normal_path = os.path.join(DATA_DIR, "listings_sale_normal.csv")

    anomalies.to_csv(anomalies_path, index=False, encoding="utf-8-sig")
    normal.to_csv(normal_path, index=False, encoding="utf-8-sig")

    print(f"\nتم الحفظ:")
    print(f"  الشاذ: {anomalies_path}")
    print(f"  الطبيعي: {normal_path}")
    print("\n⚠️  راجع ملف الشاذ يدويًا -- بعضها قد يكون فرص حقيقية (سعر بخس) مو أخطاء بيانات!")


if __name__ == "__main__":
    main()
