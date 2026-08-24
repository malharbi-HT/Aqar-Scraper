"""
فحص جودة شامل لبيانات الأنواع الخمسة (فلل/أدوار/أراضي/عمائر/مكاتب) بعد السحب.

يغطي: حجم البيانات وتوزيعها، نسبة القيم الفاضية، نطاقات منطقية للأرقام،
تكرار متبقي، وعينة عشوائية للمراجعة اليدوية.
"""

import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

TYPES = {
    "villa": "فلل",
    "floor": "أدوار",
    "land": "أراضي",
    "building": "عمائر",
    "office": "مكاتب",
}

# نطاقات منطقية تقريبية لكل نوع (سعر بالريال، مساحة بالمتر) -- للكشف عن شذوذ واضح
SANITY_RANGES = {
    "villa":    {"price": (200_000, 30_000_000), "area_sqm": (100, 3_000)},
    "floor":    {"price": (150_000, 5_000_000),  "area_sqm": (50, 1_000)},
    "land":     {"price": (50_000, 100_000_000), "area_sqm": (50, 50_000)},
    "building": {"price": (500_000, 100_000_000),"area_sqm": (150, 10_000)},
    "office":   {"price": (100_000, 20_000_000), "area_sqm": (20, 2_000)},
}


def check_type(key, name):
    path = os.path.join(DATA_DIR, f"listings_{key}.csv")
    print(f"\n{'='*60}\n{name} ({key})\n{'='*60}")

    if not os.path.exists(path):
        print(f"تحذير: ما لقيت {path}")
        return

    df = pd.read_csv(path, encoding="utf-8-sig")

    # 1) الحجم والتوزيع
    print(f"\n--- 1) الحجم والتوزيع ---")
    print(f"إجمالي الصفوف: {len(df)}")
    if "district" in df.columns:
        print(f"عدد الأحياء الفريدة: {df['district'].nunique()}")
        print("أعلى 5 أحياء بعدد الإعلانات:")
        print(df["district"].value_counts().head(5).to_string())

    # 2) نسبة القيم الفاضية
    print(f"\n--- 2) نسبة القيم الفاضية (أهم الأعمدة) ---")
    key_cols = [c for c in ["price", "area_sqm", "district", "description", "rooms", "bathrooms"] if c in df.columns]
    for col in key_cols:
        missing_pct = df[col].isna().mean() * 100
        print(f"  {col}: {missing_pct:.1f}% فاضي")

    # 3) نطاقات منطقية (كشف شذوذ واضح)
    print(f"\n--- 3) نطاقات منطقية ---")
    ranges = SANITY_RANGES.get(key, {})
    for col, (low, high) in ranges.items():
        if col not in df.columns:
            continue
        out_of_range = df[(df[col].notna()) & ((df[col] < low) | (df[col] > high))]
        print(f"  {col}: خارج النطاق المنطقي ({low:,}-{high:,}): {len(out_of_range)} صف ({len(out_of_range)/len(df)*100:.1f}%)")
        if len(out_of_range) > 0:
            print(f"    عينة (أعلى 3 قيم متطرفة): {sorted(out_of_range[col].dropna().tolist(), reverse=True)[:3]}")

    # 4) تكرار متبقي
    print(f"\n--- 4) تكرار متبقي ---")
    if "listing_id" in df.columns:
        dup_count = df["listing_id"].duplicated().sum()
        print(f"  صفوف مكررة (نفس listing_id): {dup_count}")
    else:
        print("  عمود listing_id غير موجود، تخطينا الفحص")

    # 5) عينة عشوائية للمراجعة اليدوية
    print(f"\n--- 5) عينة عشوائية (3 صفوف) ---")
    sample_cols = [c for c in ["listing_id", "title", "district", "price", "area_sqm", "url"] if c in df.columns]
    if len(df) > 0:
        print(df[sample_cols].sample(min(3, len(df)), random_state=42).to_string(index=False))


def main():
    for key, name in TYPES.items():
        check_type(key, name)


if __name__ == "__main__":
    main()
