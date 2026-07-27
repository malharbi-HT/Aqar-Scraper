"""
يمر على كل صفحات القوائم (بدون فتح تفاصيل كل إعلان -- سريع)
ويحفظ قائمة كاملة بكل أرقام الإعلانات الموجودة حاليًا بالموقع.

مهم: الموقع يفرض حد أقصى على عمق الترقيم (Pagination Depth) لكل تصنيف --
لو طلبنا "كل شمال الرياض" دفعة وحدة، يتوقف الموقع عن إرجاع نتائج بعد حوالي
120-190 صفحة حتى لو فيه أكثر فعليًا. الحل: نمسح كل حي لحاله (أصغر بكثير،
يبقى تحت حد العمق)، بدل ما نطلب المنطقة كاملة دفعة وحدة.
"""

import requests
from bs4 import BeautifulSoup
import re
import time
import os
import csv
from urllib.parse import urljoin

BASE_URL = "https://sa.aqar.fm"

DIRECTIONS = {
    "شمال الرياض": "https://sa.aqar.fm/شقق-للإيجار/الرياض/شمال-الرياض",
    "شرق الرياض": "https://sa.aqar.fm/شقق-للإيجار/الرياض/شرق-الرياض",
    "غرب الرياض": "https://sa.aqar.fm/شقق-للإيجار/الرياض/غرب-الرياض",
    "جنوب الرياض": "https://sa.aqar.fm/شقق-للإيجار/الرياض/جنوب-الرياض",
    "وسط الرياض": "https://sa.aqar.fm/شقق-للإيجار/الرياض/وسط-الرياض",
}
MAX_PAGES_PER_DISTRICT = 200  # سقف آمن لكل حي لحاله (أحياء كبيرة جدًا نادرة تتجاوزه)

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
OUTPUT_PATH = os.path.join(DATA_DIR, "active_ids_today_rent.csv")


def is_forbidden(path):
    return any(path.startswith(p) for p in FORBIDDEN_PATH_PREFIXES)


def extract_listing_id(url):
    match = re.search(r"-(\d+)/?$", url)
    return match.group(1) if match else url


def fetch_html(url):
    last_error = None
    for attempt in range(1, 6):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            last_error = e
            print(f"    محاولة {attempt} فشلت لـ {url}: {e}")
            if attempt < 5:
                time.sleep(5 * attempt)
    raise last_error


def discover_districts(direction_url):
    """يجيب كل روابط الأحياء المذكورة بصفحة المنطقة (تظهر مرتين أحيانًا، ندمجهم)"""
    html = fetch_html(direction_url)
    soup = BeautifulSoup(html, "html.parser")

    districts = {}  # district_url -> name
    for a in soup.select("a[href]"):
        href = a["href"]
        full = urljoin(BASE_URL, href)
        if "/حي-" not in full and "حي" not in full:
            continue
        # لازم يكون امتداد مباشر لرابط المنطقة نفسها (حي تابع لها)
        if not full.startswith(direction_url + "/"):
            continue
        # نتأكد ما فيه أرقام إعلان أو صفحات بنهاية الرابط (يعني رابط حي نظيف)
        tail = full[len(direction_url) + 1:]
        if "/" in tail or re.search(r"-\d{4,}$", tail):
            continue
        districts[full] = a.get_text(strip=True)

    return districts


def collect_listing_links_from_list_page(url):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
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


def crawl_one_url(base_url, all_records, failed_counter):
    """يمسح كل صفحات رابط وحد (حي أو منطقة صغيرة) حتى صفحتين فاضيتين متتاليتين"""
    consecutive_empty = 0
    for page_num in range(1, MAX_PAGES_PER_DISTRICT + 1):
        page_url = base_url if page_num == 1 else f"{base_url}/{page_num}"
        try:
            links = collect_listing_links_from_list_page(page_url)
        except requests.RequestException as e:
            print(f"  ⚠️  فشلت الصفحة نهائيًا: {page_url}: {e}")
            failed_counter[0] += 1
            time.sleep(10)
            continue
        if not links:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
            time.sleep(2)
            continue
        consecutive_empty = 0
        for link in links:
            all_records[extract_listing_id(link)] = link
        time.sleep(1.5)
    return page_num - consecutive_empty


def main():
    all_records = {}
    failed_counter = [0]

    for direction_name, direction_url in DIRECTIONS.items():
        print(f"\n=== المنطقة: {direction_name} ===")
        districts = discover_districts(direction_url)
        print(f"لقينا {len(districts)} حي بهذي المنطقة")

        before_direction = len(all_records)

        # 1) نمسح كل حي لحاله (تحت حد العمق دائمًا لأنها أصغر)
        for district_url, district_name in districts.items():
            last_page = crawl_one_url(district_url, all_records, failed_counter)
            print(f"  {district_name}: توقفنا صفحة {last_page} -- إجمالي تراكمي {len(all_records)}")
            time.sleep(1)

        # 2) نمسح كمان صفحات المنطقة نفسها (بدون فلتر حي) لأول عدد صفحات آمن،
        #    عشان نلقط أي إعلان "بدون حي محدد" ما ظهر بقائمة الأحياء أعلاه
        last_page = crawl_one_url(direction_url, all_records, failed_counter)
        print(f"  (فحص عام للمنطقة كاملة): توقفنا صفحة {last_page}")

        added = len(all_records) - before_direction
        print(f"✅ {direction_name}: أضفنا {added} إعلان جديد (إجمالي تراكمي: {len(all_records)})")

    if failed_counter[0]:
        print(f"\n⚠️  تحذير: {failed_counter[0]} صفحة فشلت نهائيًا بكل التشغيلة")

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
