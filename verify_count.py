"""
يقارن عدد العقارات النشطة عندنا (listings_sale_active_only.csv) مع العدد
الحقيقي الفعلي بالموقع -- مستخرج من active_ids_today.csv (ناتج crawl_active_ids.py
اللي يمسح كل صفحات القوائم فعليًا، مو صفحة ملخص معقدة).

الترتيب المطلوب قبل تشغيل هذا السكربت:
1. crawl_active_ids.py   -> data/active_ids_today.csv
2. track_status.py       -> data/listings_sale_status.csv
3. filter_active_only.py -> data/listings_sale_active_only.csv
4. verify_count.py (هذا الملف)
"""

import pandas as pd
import os
import time
from urllib.parse import unquote

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ACTIVE_IDS_PATH = os.path.join(DATA_DIR, "active_ids_today.csv")
ACTIVE_ONLY_PATH = os.path.join(DATA_DIR, "listings_sale_active_only.csv")
RAW_PATH = os.path.join(DATA_DIR, "listings_sale.csv")
LISTINGS_PATH = ACTIVE_ONLY_PATH if os.path.exists(ACTIVE_ONLY_PATH) else RAW_PATH

BASE_URL = "https://sa.aqar.fm"
DIRECTIONS = ["شمال الرياض", "شرق الرياض", "غرب الرياض", "جنوب الرياض", "وسط الرياض"]


def parse_direction_from_url(url):
    """يستخرج الاتجاه من مسار الرابط (نفس منطق السكربتات الأساسية)"""
    path = unquote(str(url).replace(BASE_URL, "")).strip("/")
    parts = path.split("/")
    return parts[2].replace("-", " ") if len(parts) > 2 else None


def main():
    if not os.path.exists(ACTIVE_IDS_PATH):
        print(f"تحذير: ما لقيت {ACTIVE_IDS_PATH}")
        print("لازم تشغّل crawl_active_ids.py أول -- هو مصدر 'العدد الحقيقي بالموقع'")
        return

    print(f"تاريخ التحقق: {time.strftime('%Y-%m-%d %H:%M')}")

    site_df = pd.read_csv(ACTIVE_IDS_PATH, encoding="utf-8-sig")
    site_df["direction"] = site_df["url"].apply(parse_direction_from_url)
    site_counts = site_df["direction"].value_counts().to_dict()

    used_file = os.path.basename(LISTINGS_PATH)
    if LISTINGS_PATH == ACTIVE_ONLY_PATH:
        print(f"المصدر عندنا: {used_file} (النشط فقط) ✓")
    else:
        print(f"المصدر عندنا: {used_file} (⚠️ الخام المتراكم -- شغّل filter_active_only.py أول لمقارنة أدق)")

    df = pd.read_csv(LISTINGS_PATH, encoding="utf-8-sig")
    scraped_counts = df["direction"].value_counts().to_dict()

    if "date_scraped" in df.columns:
        dates = pd.to_datetime(df["date_scraped"], errors="coerce")
        if dates.notna().any():
            print(f"تاريخ أقدم سحب بالبيانات: {dates.min().date()}")
            print(f"تاريخ آخر سحب بالبيانات: {dates.max().date()}")

    print(f"\n{'المنطقة':<15}{'بالموقع (فعلي)':>16}{'عندنا':>12}{'الفرق':>12}")
    print("-" * 60)

    total_site, total_scraped = 0, 0
    for direction in DIRECTIONS:
        site_n = site_counts.get(direction, 0)
        scraped_n = scraped_counts.get(direction, 0)
        diff = scraped_n - site_n
        total_site += site_n
        total_scraped += scraped_n
        flag = "✓" if abs(diff) <= 20 else "⚠️"
        print(f"{direction:<15}{site_n:>16,}{scraped_n:>12,}{diff:>+12,} {flag}")

    print("-" * 60)
    total_diff = total_scraped - total_site
    print(f"{'الإجمالي':<15}{total_site:>16,}{total_scraped:>12,}{total_diff:>+12,}")

    pct = (total_scraped / total_site * 100) if total_site else 0
    print(f"\nنسبة التغطية: {pct:.1f}%")

    history_path = os.path.join(DATA_DIR, "verify_count_history.csv")
    history_row = {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "total_site": total_site,
        "total_scraped": total_scraped,
        "coverage_pct": round(pct, 1),
    }
    for direction in DIRECTIONS:
        history_row[f"site_{direction}"] = site_counts.get(direction, 0)
        history_row[f"scraped_{direction}"] = scraped_counts.get(direction, 0)

    history_df = pd.DataFrame([history_row])
    if os.path.exists(history_path):
        history_df.to_csv(history_path, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        history_df.to_csv(history_path, index=False, encoding="utf-8-sig")
    print(f"تم إضافة السجل لـ {history_path}")


if __name__ == "__main__":
    main()
