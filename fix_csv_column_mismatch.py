"""
يصلح listings_sale.csv بعد إضافة أعمدة جديدة للسكربت (published, price_text,
price_was_missing) -- المشكلة: الصفوف القديمة مكتوبة بعدد أعمدة أقل من الجديدة،
فيفشل pandas.read_csv بخطأ "Expected N fields, saw M".

الحل: نقرأ الملف صف صف (بدون الاعتماد على استنتاج pandas التلقائي)، ونوحّد
الكل لنفس عدد الأعمدة (نعبي القيم الناقصة بفراغ)، ونعيد الحفظ برأس محدّث.
"""

import csv
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TARGET_CSV = os.path.join(DATA_DIR, "listings_sale.csv")

# نفس قائمة الأعمدة الحالية بالسكربت (لازم تطابق CSV_FIELDS بـ scraper_sale.py بالضبط)
FULL_FIELDS = [
    "listing_id", "url", "title", "price", "area_sqm",
    "rooms", "bathrooms", "livings", "age_years", "district", "city", "direction",
    "description", "latitude", "longitude", "images", "images_count",
    "advertiser_name", "advertiser_company", "advertiser_type",
    "created_at", "published_at", "last_update", "views", "date_scraped",
    "published", "price_text", "price_was_missing",
]


def main():
    if not os.path.exists(TARGET_CSV):
        print(f"تحذير: ما لقيت {TARGET_CSV}")
        return

    backup_path = TARGET_CSV + ".backup"
    os.replace(TARGET_CSV, backup_path)
    print(f"نسخة احتياطية محفوظة: {backup_path}")

    fixed_rows = []
    old_header = None
    with open(backup_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        old_header = next(reader)
        old_col_count = len(old_header)
        print(f"عدد أعمدة الرأس القديم: {old_col_count}")

        for i, row in enumerate(reader, start=2):
            if len(row) < len(FULL_FIELDS):
                row = row + [""] * (len(FULL_FIELDS) - len(row))
            elif len(row) > len(FULL_FIELDS):
                row = row[:len(FULL_FIELDS)]
            fixed_rows.append(row)

    print(f"عدد الصفوف المُصلَحة: {len(fixed_rows)}")

    with open(TARGET_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(FULL_FIELDS)
        writer.writerows(fixed_rows)

    print(f"تم حفظ الملف المُصلَح: {TARGET_CSV}")


if __name__ == "__main__":
    main()
