"""
يقارن عدد العقارات (شقق للبيع) اللي عندنا بالبيانات المسحوبة، مع العدد
الحقيقي المعروض حاليًا بموقع aqar.fm لكل منطقة بالرياض -- ويطلع تقرير فرق دقيق.
"""

import requests
import re
import pandas as pd
import os
import time

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ACTIVE_ONLY_PATH = os.path.join(DATA_DIR, "listings_sale_active_only.csv")
RAW_PATH = os.path.join(DATA_DIR, "listings_sale.csv")
LISTINGS_PATH = ACTIVE_ONLY_PATH if os.path.exists(ACTIVE_ONLY_PATH) else RAW_PATH

BASE_LIST_URL = "https://sa.aqar.fm/شقق-للبيع/الرياض"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.8",
}

DIRECTIONS = ["شمال الرياض", "شرق الرياض", "غرب الرياض", "جنوب الرياض", "وسط الرياض"]

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# نمط مرن: يدعم مسافات غير قياسية (nbsp) وفواصل عربية/إنجليزية
COUNT_PATTERN = re.compile(
    r"({})[\s\u00a0]*\(([\d\u0660-\u0669,\u066c]+)\)".format("|".join(DIRECTIONS))
)


def fetch_site_counts():
    """يجيب العدد الحقيقي لكل منطقة من صفحة الموقع مباشرة"""
    last_error = None
    for attempt in range(1, 4):
        try:
            resp = requests.get(BASE_LIST_URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            last_error = e
            if attempt < 3:
                time.sleep(3 * attempt)
    else:
        raise last_error

    counts = {}
    normalized_text = resp.text.translate(ARABIC_DIGITS).replace(",", "").replace("\u066c", "")
    # نطبّق النمط على النص الأصلي (للأسماء) لكن نستخرج الرقم من نفس الموضع بالنص المطبّع
    for match in re.finditer(
        r"({})[\s\u00a0]*\(([\d,]+)\)".format("|".join(DIRECTIONS)), normalized_text
    ):
        direction = match.group(1)
        count = int(match.group(2))
        if direction not in counts:
            counts[direction] = count

    if not counts:
        print("تحذير: ما لقينا أي عدد. عينة من أول 500 حرف بالصفحة للتشخيص:")
        print(resp.text[:500])

    return counts


def main():
    print(f"تاريخ التحقق: {time.strftime('%Y-%m-%d %H:%M')}")
    used_file = os.path.basename(LISTINGS_PATH)
    if LISTINGS_PATH == ACTIVE_ONLY_PATH:
        print(f"المصدر: {used_file} (النشط فقط) ✓")
    else:
        print(f"المصدر: {used_file} (⚠️ الخام المتراكم -- شغّل track_status.py + filter_active_only.py أول لمقارنة أدق)")
    print("نجيب الأعداد الحقيقية من الموقع...")
    site_counts = fetch_site_counts()

    if not site_counts:
        print("تحذير: ما قدرنا نستخرج أي عدد من صفحة الموقع -- تأكد الرابط أو الصيغة لسا صحيحة")
        return

    df = pd.read_csv(LISTINGS_PATH, encoding="utf-8-sig")
    scraped_counts = df["direction"].value_counts().to_dict()

    if "date_scraped" in df.columns:
        dates = pd.to_datetime(df["date_scraped"], errors="coerce")
        if dates.notna().any():
            print(f"تاريخ أقدم سحب بالبيانات: {dates.min().date()}")
            print(f"تاريخ آخر سحب بالبيانات: {dates.max().date()}")

    print(f"\n{'المنطقة':<15}{'بالموقع':>12}{'عندنا':>12}{'الفرق':>12}")
    print("-" * 55)

    total_site, total_scraped = 0, 0
    for direction in DIRECTIONS:
        site_n = site_counts.get(direction, 0)
        scraped_n = scraped_counts.get(direction, 0)
        diff = scraped_n - site_n
        total_site += site_n
        total_scraped += scraped_n
        flag = "✓" if abs(diff) <= 20 else "⚠️"
        print(f"{direction:<15}{site_n:>12,}{scraped_n:>12,}{diff:>+12,} {flag}")

    print("-" * 55)
    total_diff = total_scraped - total_site
    print(f"{'الإجمالي':<15}{total_site:>12,}{total_scraped:>12,}{total_diff:>+12,}")

    pct = (total_scraped / total_site * 100) if total_site else 0
    print(f"\nنسبة التغطية: {pct:.1f}%")

    # نحفظ سجل تاريخي لكل تشغيلة تحقق -- يساعد نتابع تحسّن التغطية بمرور الوقت
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
