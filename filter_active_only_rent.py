"""
يفلتر listings_sale.csv (اللي يتراكم بدون حذف) ويبقي بس العقارات
المصنّفة "جديد" أو "نشط" حسب آخر تحديث بجدول الحالة (listings_sale_status.csv)
-- يعني يستبعد أي عقار محتمل انباع أو انحذف من الموقع.
"""

import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LISTINGS_PATH = os.path.join(DATA_DIR, "listings_rent_clean.csv")
STATUS_PATH = os.path.join(DATA_DIR, "listings_rent_status.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "listings_rent_active_only.csv")


def main():
    if not os.path.exists(STATUS_PATH):
        print(f"تحذير: ما لقيت {STATUS_PATH} -- شغّل track_status.py أول")
        return

    listings = pd.read_csv(LISTINGS_PATH, encoding="utf-8-sig")
    status = pd.read_csv(STATUS_PATH, encoding="utf-8-sig")

    listings["listing_id"] = listings["listing_id"].astype(str)
    status["listing_id"] = status["listing_id"].astype(str)

    print(f"إجمالي العقارات المتراكمة: {len(listings)}")

    active_ids = set(status[status["status"].isin(["جديد", "نشط"])]["listing_id"])
    print(f"عقارات نشطة حاليًا حسب جدول الحالة: {len(active_ids)}")

    active_listings = listings[listings["listing_id"].isin(active_ids)]
    removed_count = len(listings) - len(active_listings)

    print(f"استبعدنا {removed_count} عقار (محتمل مباع/محذوف أو ما وصله التتبع بعد)")
    print(f"العدد النهائي النشط: {len(active_listings)}")

    active_listings.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
