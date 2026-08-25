"""
ينظّف بيانات الأنواع الخمسة (فلل/أدوار/أراضي/عمائر/مكاتب) من القيم الشاذة
(سعر أو مساحة خارج النطاق المنطقي)، ويفصلهم لملف منفصل للمراجعة اليدوية --
بنفس منهجية detect_anomalies.py المستخدمة بالشقق (نفصل، مو نحذف نهائيًا).
"""

import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

TYPES = ["villa", "floor", "land", "building", "office"]

# نفس النطاقات المعتمدة بـ check_property_types_quality.py (بعد التعديل الأخير)
SANITY_RANGES = {
    "villa":    {"price": (200_000, 30_000_000), "area_sqm": (100, 3_000)},
    "floor":    {"price": (150_000, 5_000_000),  "area_sqm": (50, 1_000)},
    "land":     {"price": (10_000, 500_000_000), "area_sqm": (50, 50_000)},
    "building": {"price": (500_000, 200_000_000),"area_sqm": (100, 10_000)},
    "office":   {"price": (100_000, 20_000_000), "area_sqm": (20, 2_000)},
}


def clean_type(key):
    path = os.path.join(DATA_DIR, f"listings_{key}.csv")
    if not os.path.exists(path):
        print(f"{key}: ما لقيت {path}، نتخطاه")
        return

    df = pd.read_csv(path, encoding="utf-8-sig")
    before = len(df)

    ranges = SANITY_RANGES[key]
    is_anomaly = pd.Series(False, index=df.index)
    for col, (low, high) in ranges.items():
        if col not in df.columns:
            continue
        out = df[col].notna() & ((df[col] < low) | (df[col] > high))
        is_anomaly = is_anomaly | out

    normal = df[~is_anomaly].copy()
    anomalies = df[is_anomaly].copy()

    normal_path = os.path.join(DATA_DIR, f"listings_{key}_normal.csv")
    anomalies_path = os.path.join(DATA_DIR, f"listings_{key}_anomalies.csv")
    normal.to_csv(normal_path, index=False, encoding="utf-8-sig")
    anomalies.to_csv(anomalies_path, index=False, encoding="utf-8-sig")

    print(f"{key}: {before} إجمالي → {len(normal)} طبيعي، {len(anomalies)} شاذ ({len(anomalies)/before*100:.1f}%)")


def main():
    for key in TYPES:
        clean_type(key)


if __name__ == "__main__":
    main()
