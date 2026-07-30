"""
يصحح عدد الغرف والحمامات الفاضية أو صفر بالغلط ببيانات البيع، من نص الوصف.
يجي بعد cross_check_area.py وقبل detect_anomalies.py بخط تنظيف البيع.
"""

import pandas as pd
import os
from fix_rooms_bathrooms_nlp import extract_bathrooms_from_description, extract_rooms_from_description

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CROSSCHECKED_PATH = os.path.join(DATA_DIR, "listings_sale_area_crosschecked.csv")
PRICE_FIXED_PATH = os.path.join(DATA_DIR, "listings_sale_price_fixed.csv")
INPUT_PATH = CROSSCHECKED_PATH if os.path.exists(CROSSCHECKED_PATH) else PRICE_FIXED_PATH
OUTPUT_PATH = os.path.join(DATA_DIR, "listings_sale_rooms_fixed.csv")


def main():
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"نقرأ من: {INPUT_PATH}")
    print(f"عدد الصفوف: {len(df)}")

    missing_bath = df[df["bathrooms"].isna() | (df["bathrooms"] == 0)]
    fixed_bath = 0
    for idx in missing_bath.index:
        val = extract_bathrooms_from_description(df.loc[idx, "description"])
        if val:
            df.at[idx, "bathrooms"] = val
            fixed_bath += 1

    missing_rooms = df[df["rooms"].isna() | (df["rooms"] == 0)]
    fixed_rooms = 0
    for idx in missing_rooms.index:
        val = extract_rooms_from_description(df.loc[idx, "description"])
        if val:
            df.at[idx, "rooms"] = val
            fixed_rooms += 1

    print(f"صححنا {fixed_bath} حمام من أصل {len(missing_bath)} فاضي/صفر")
    print(f"صححنا {fixed_rooms} غرفة من أصل {len(missing_rooms)} فاضي/صفر")

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
