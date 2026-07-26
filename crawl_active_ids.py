"""
يمر على كل صفحات القوائم (بدون فتح تفاصيل كل إعلان -- سريع)
ويحفظ قائمة كاملة بكل أرقام الإعلانات الموجودة حاليًا بالموقع لكل منطقة.
يُستخدم كأساس لمقارنة يومية (جديد / نشط / محتمل محذوف) عبر track_status.py
"""

import requests
from bs4 import BeautifulSoup
import re
import time
import os
import csv
from urllib.parse import urljoin

BASE_URL = "https://sa.aqar.fm"

LIST_PAGES = [
    "https://sa.aqar.fm/شقق-للبيع/الرياض/شمال-الرياض",
    "https://sa.aqar.fm/شقق-للبيع/الرياض/شرق-الرياض",
    "https://sa.aqar.fm/شقق-للبيع/الرياض/غرب-الرياض",
    "https://sa.aqar.fm/شقق-للبيع/الرياض/جنوب-الرياض",
    "https://sa.aqar.fm/شقق-للبيع/الرياض/وسط-الرياض",
]
MAX_PAGES_PER_CATEGORY = 500  # بدون توقف مبكر -- نبي مسح كامل لكل الموجود حاليًا

FORBIDDEN_PATH_PREFIXES = [
    "/contact-us", "/اتصل-بنا", "/معلومات-المعلن", "/contact_user",
    "/send_iphone", "/send_android", "/download_app",
    "/search/", "/regions/", "/view/", "/map/", "/map-ad/",
    "/district/", "/direction/", "/city/",
    "/add-listing/", "/add-rega-listing/", "/editlisting/",
    "/user/bookings", "/financing/application", "/login",
    "/graphql", "/auth-graphql",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.8",
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "active_ids_today.csv")


def is_forbidden(path):
    return any(path.startswith(p) for p in FORBIDDEN_PATH_PREFIXES)


def extract_listing_id(url):
    match = re.search(r"-(\d+)/?$", url)
    return match.group(1) if match else url


def collect_listing_links_from_list_page(url):
    last_error = None
    for attempt in range(1, 6):  # رفعناها لـ5 محاولات (كانت 3)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            last_error = e
            print(f"    محاولة {attempt} فشلت لـ {url}: {e}")
            if attempt < 5:
                time.sleep(5 * attempt)  # تأخير أطول (5، 10، 15، 20 ثانية)
    else:
        raise last_error
    soup = BeautifulSoup(resp.text, "html.parser")
    links = set()
    for a in soup.select("a[href]"):
        href = a["href"]
        full = urljoin(BASE_URL, href)
        path = full.replace(BASE_URL, "")
        if is_forbidden(path):
            continue
        if re.search(r"-\d{5,}/?$", full):
            links.add(full)
    return links


def main():
    all_records = {}  # listing_id -> url
    failed_pages_total = 0

    for base in LIST_PAGES:
        print(f"=== تصنيف: {base} ===")
        failed_pages_this_direction = 0
        consecutive_empty = 0
        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
            page_url = base if page_num == 1 else f"{base}/{page_num}"
            try:
                links = collect_listing_links_from_list_page(page_url)
            except requests.RequestException as e:
                print(f"⚠️  فشلت الصفحة نهائيًا بعد كل المحاولات: {page_url}: {e}")
                failed_pages_this_direction += 1
                failed_pages_total += 1
                time.sleep(10)  # نعطي راحة إضافية للسيرفر بعد فشل متكرر
                continue
            if not links:
                consecutive_empty += 1
                print(f"صفحة {page_num}: فاضية (متتالية: {consecutive_empty})")
                if consecutive_empty >= 2:
                    print(f"وصلنا آخر صفحة عند صفحة {page_num - consecutive_empty}")
                    break
                time.sleep(2)
                continue
            consecutive_empty = 0
            for link in links:
                all_records[extract_listing_id(link)] = link
            print(f"صفحة {page_num}: إجمالي حتى الآن {len(all_records)}")
            time.sleep(2)

        if failed_pages_this_direction:
            print(f"⚠️  {base}: {failed_pages_this_direction} صفحة فشلت نهائيًا (~{failed_pages_this_direction * 25} إعلان محتمل مفقود)")

    if failed_pages_total:
        print(f"\n{'='*50}")
        print(f"⚠️  تحذير: {failed_pages_total} صفحة فشلت نهائيًا بكل التصنيفات")
        print(f"⚠️  هذا يعني احتمال نقص ~{failed_pages_total * 25} إعلان بالعدد النهائي")
        print(f"{'='*50}")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["listing_id", "url"])
        for lid, url in all_records.items():
            writer.writerow([lid, url])

    print(f"\nإجمالي الإعلانات النشطة حاليًا بالموقع: {len(all_records)}")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
