"""
يدمج ملفات البيع الخمسة (شمال/شرق/غرب/جنوب/وسط الرياض) بملف واحد نظيف
يزيل التكرار لو أي إعلان تكرر بين الملفات (احتياط، نادر الحدوث)
"""

import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

REGION_FILES = [
    "listings_sale_north.csv",
    "listings_sale_east.csv",
    "listings_sale_west.csv",
    "listings_sale_south.csv",
    "listings_sale_center.csv",
]


def main():
    dfs = []
    merged_regions = []
    missing_regions = []

    for filename in REGION_FILES:
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            print(f"تحذير: ما لقيت {filename}، نتخطاه")
            missing_regions.append(filename)
            continue
        df = pd.read_csv(path, encoding="utf-8-sig")
        print(f"{filename}: {len(df)} صف")
        dfs.append(df)
        merged_regions.append(filename)

    if not dfs:
        print("ما فيه أي ملف متاح للدمج!")
        return

    merged = pd.concat(dfs, ignore_index=True)
    before_dedup = len(merged)
    merged = merged.drop_duplicates(subset="listing_id", keep="last")
    after_dedup = len(merged)

    if before_dedup != after_dedup:
        print(f"حذفنا {before_dedup - after_dedup} صف مكرر بين الملفات")

    out_path = os.path.join(DATA_DIR, "listings_sale.csv")
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"\n{'='*50}")
    print("ملخص الدمج")
    print(f"{'='*50}")
    print(f"✅ اندمجت بنجاح ({len(merged_regions)}):")
    for r in merged_regions:
        print(f"   - {r}")
    if missing_regions:
        print(f"\n❌ ما اندمجت (الملف مو موجود) ({len(missing_regions)}):")
        for r in missing_regions:
            print(f"   - {r}")
    else:
        print("\n❌ ما اندمجت: لا شي -- كل المناطق موجودة ✓")
    print(f"\nالإجمالي النهائي: {len(merged)} صف -> {out_path}")


if __name__ == "__main__":
    main()
