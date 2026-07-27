"""
يدرّب نموذج Random Forest يتوقع الإيجار السنوي المناسب لعقار بناءً على خصائصه.
تحسينات عن النسخة الأولى:
- ترميز الحي بمتوسط سعره (Target Encoding) بدل One-Hot -- يعكس قيمة الحي الفعلية
  بعمود واحد قوي، بدل يتشتت على مئات أعمدة نادرة
- ميزة إضافية: هل الشقة مفروشة (تأثير كبير على الإيجار، مستخرجة من الوصف)
"""

import pandas as pd
import numpy as np
import re
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
import os
import joblib

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "listings_rent_clean.csv")
MODEL_PATH = os.path.join(DATA_DIR, "rent_model.joblib")
DISTRICT_ENCODING_PATH = os.path.join(DATA_DIR, "rent_model_district_encoding.joblib")

FURNISHED_PATTERN = re.compile(r"مفروش|مؤثث")

FEATURE_COLS = [
    "area_sqm", "rooms", "bathrooms", "livings", "age_years",
    "latitude", "longitude", "district_encoded", "is_furnished",
]
TARGET_COL = "price"


def add_furnished_flag(df):
    df["is_furnished"] = df["description"].fillna("").str.contains(FURNISHED_PATTERN).astype(int)
    return df


def encode_district(df, district_encoding=None):
    """يستبدل اسم الحي برقم واحد يمثل متوسط سعره (Target Encoding).
    لو district_encoding معطى (وقت التطبيق لاحقًا)، نستخدمه بدل نحسبه من جديد."""
    if district_encoding is None:
        district_encoding = df.groupby("district")[TARGET_COL].median()
    global_median = df[TARGET_COL].median()
    df["district_encoded"] = df["district"].map(district_encoding).fillna(global_median)
    return df, district_encoding


def main():
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"عدد الصفوف الكلي: {len(df)}")

    required_cols = ["area_sqm", "rooms", "bathrooms", "livings", "age_years",
                      "latitude", "longitude", "district", TARGET_COL]
    before = len(df)
    df = df.dropna(subset=required_cols)
    print(f"بعد حذف الصفوف الناقصة بأعمدة أساسية: {len(df)} (حذفنا {before - len(df)})")

    df = add_furnished_flag(df)
    print(f"شقق مفروشة: {df['is_furnished'].sum()} من {len(df)}")

    # نقسّم البيانات أول، ونحسب ترميز الحي من التدريب بس (نتفادى تسرّب بيانات الاختبار)
    train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)

    train_df, district_encoding = encode_district(train_df)
    test_df, _ = encode_district(test_df, district_encoding=district_encoding)

    X_train = train_df[FEATURE_COLS]
    y_train = train_df[TARGET_COL]
    X_test = test_df[FEATURE_COLS]
    y_test = test_df[TARGET_COL]

    print(f"بيانات التدريب: {len(X_train)} | بيانات الاختبار: {len(X_test)}")

    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=20,
        min_samples_leaf=3,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    mape = np.mean(np.abs((y_test - y_pred) / y_test)) * 100

    print(f"\n--- تقييم النموذج (على بيانات الاختبار) ---")
    print(f"متوسط الخطأ المطلق (MAE): {mae:,.0f} ريال")
    print(f"متوسط نسبة الخطأ (MAPE): {mape:.1f}%")
    print(f"R² (نسبة التباين المفسّر): {r2:.3f}")

    importances = pd.Series(model.feature_importances_, index=X_train.columns).sort_values(ascending=False)
    print(f"\n--- أهمية الخصائص (مرتبة) ---")
    print(importances.to_string())

    joblib.dump(model, MODEL_PATH)
    joblib.dump(district_encoding, DISTRICT_ENCODING_PATH)
    print(f"\nتم حفظ النموذج: {MODEL_PATH}")
    print(f"تم حفظ ترميز الأحياء: {DISTRICT_ENCODING_PATH}")


if __name__ == "__main__":
    main()
