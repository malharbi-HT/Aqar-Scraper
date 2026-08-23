"""
يدمج كل ملفات الأحياء المنفصلة (data/districts/listings_<type>_<حي>.csv) بملف
نهائي واحد لكل نوع عقار، ويحذف التكرار حسب listing_id.
"""

import pandas as pd
import os
import glob

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DISTRICTS_DIR = os.path.join(DATA_DIR, "districts")

PROPERTY_KEYS = ["villa", "floor", "land", "building", "office"]


def main():
    for key in PROPERTY_KEYS:
        pattern = os.path.join(DISTRICTS_DIR, f"listings_{key}_*.csv")
        district_files = glob.glob(pattern)

        if not district_files:
            print(f"{key}: ما لقيت أي ملف حي، نتخطاه")
            continue

        dfs = []
        for f in district_files:
            df = pd.read_csv(f, encoding="utf-8-sig")
            dfs.append(df)
        print(f"{key}: قرأنا {len(district_files)} ملف حي، إجمالي {sum(len(d) for d in dfs)} صف قبل الدمج")

        merged = pd.concat(dfs, ignore_index=True)
        before = len(merged)
        if "listing_id" in merged.columns:
            merged = merged.drop_duplicates(subset="listing_id", keep="first")
        print(f"{key}: بعد حذف التكرار: {len(merged)} صف (كان {before})")

        output_path = os.path.join(DATA_DIR, f"listings_{key}.csv")
        merged.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"{key}: تم الحفظ بـ {output_path}\n")


if __name__ == "__main__":
    main()
