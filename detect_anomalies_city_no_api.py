"""
كشف الشذوذ ببيانات مدينة (المدينة المنورة أو جدة) -- نفس فكرة
detect_anomalies.py حق الرياض (IsolationForest)، بس مطبّق لكل نوع عقار
لحاله (شقة، فيلا، أرض...) عشان التوزيعات مختلفة جدًا بين الأنواع (سعر
مصنع طبيعي يعتبر شاذ لو قارناه بشقة، والعكس).

المعايير: سعر المتر (price/area_sqm) هو المؤشر الأهم -- عقار سعر متره
شاذ جدًا (غالي أو رخيص بشكل غير منطقي) مقارنة بأمثاله بنفس النوع، يُستبعد.

المخرجات:
- listings_sale_{city}_all_types_normal.csv   -- البيانات النظيفة
- listings_sale_{city}_all_types_anomalies.csv -- الشاذة (للمراجعة، مو للحذف)
"""

import pandas as pd
import numpy as np
import os
import sys
from sklearn.ensemble import IsolationForest

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

MIN_ROWS_FOR_DETECTION = 15  # لو نوع فيه أقل من كذا صف، نتخطى الكشف (عينة صغيرة جدًا للتوزيع الإحصائي)
CONTAMINATION = 0.05  # نسبة متوقعة من الشذوذ (5%) -- نفس القيمة الافتراضية المعقولة لـIsolationForest


def detect_anomalies_for_type(group):
    """يطبّق IsolationForest على مجموعة عقارات من نفس النوع، يرجع mask
    (True = طبيعي، False = شاذ)"""
    df = group.copy()
    df["price_per_sqm"] = df["price"] / df["area_sqm"].replace(0, np.nan)

    features = df[["price", "area_sqm", "price_per_sqm"]].copy()
    # نستبعد صفوف فيها قيم ناقصة من حساب الشذوذ (ما نقدر نقيّمها بدون بيانات كافية)
    valid_mask = features.notna().all(axis=1)

    if valid_mask.sum() < MIN_ROWS_FOR_DETECTION:
        # عينة صغيرة جدًا -- نعتبر الكل طبيعي (ما نقدر نحكم إحصائيًا بثقة)
        return pd.Series(True, index=df.index)

    model = IsolationForest(contamination=CONTAMINATION, random_state=42)
    predictions = model.fit_predict(features[valid_mask])
    # IsolationForest يرجع 1 = طبيعي، -1 = شاذ

    result = pd.Series(True, index=df.index)  # افتراضي: نعتبر القيم الناقصة طبيعية (ما نستبعدها بس لنقص بيانات)
    result.loc[valid_mask] = predictions == 1
    return result


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("medina", "jeddah"):
        print("الاستخدام: python detect_anomalies_city_no_api.py medina|jeddah")
        return
    city_key = sys.argv[1]

    input_path = os.path.join(DATA_DIR, f"listings_sale_{city_key}_all_types.csv")
    normal_path = os.path.join(DATA_DIR, f"listings_sale_{city_key}_all_types_normal.csv")
    anomalies_path = os.path.join(DATA_DIR, f"listings_sale_{city_key}_all_types_anomalies.csv")

    if not os.path.exists(input_path):
        print(f"تحذير: ما لقينا {input_path}")
        return

    df = pd.read_csv(input_path, encoding="utf-8-sig")
    print(f"إجمالي الإعلانات: {len(df)}")

    if "property_type" not in df.columns:
        print("تحذير: ما فيه عمود property_type -- نطبّق الكشف على الكل مع بعض")
        df["property_type"] = "الكل"

    all_normal_masks = pd.Series(True, index=df.index)

    for ptype, group in df.groupby("property_type"):
        mask = detect_anomalies_for_type(group)
        anomaly_count = (~mask).sum()
        print(f"  {ptype}: {len(group)} إعلان -- {anomaly_count} شاذ ({anomaly_count/len(group)*100:.1f}%)")
        all_normal_masks.loc[group.index] = mask

    normal_df = df[all_normal_masks].copy()
    anomalies_df = df[~all_normal_masks].copy()

    print(f"\nإجمالي طبيعي: {len(normal_df)}")
    print(f"إجمالي شاذ: {len(anomalies_df)}")

    normal_df.to_csv(normal_path, index=False, encoding="utf-8-sig")
    anomalies_df.to_csv(anomalies_path, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {normal_path}")
    print(f"تم الحفظ (للمراجعة): {anomalies_path}")


if __name__ == "__main__":
    main()
