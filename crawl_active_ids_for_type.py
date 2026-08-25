"""
يجمع IDs كل الإعلانات النشطة حاليًا بالموقع لنوع عقار معيّن (فلل/أدوار/أراضي/
عمائر/مكاتب) -- بدون سحب تفاصيل كاملة (سريع جدًا مقارنة بالسحب العادي)،
يُستخدم بس للمقارنة مع المحفوظ وتحديد الحالة (نشط/محتمل محذوف).

الاستخدام:
    python crawl_active_ids_for_type.py فلل-للبيع villa
"""

import requests
from bs4 import BeautifulSoup
import re
import sys
import csv
import time
from urllib.parse import urljoin

BASE_URL = "https://sa.aqar.fm"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.8",
}
REGIONS = ["شمال-الرياض", "شرق-الرياض", "غرب-الرياض", "جنوب-الرياض", "وسط-الرياض"]
MAX_PAGES_PER_DISTRICT = 200


def fetch_html(url):
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"    محاولة {attempt} فشلت لـ {url}: {e}")
            time.sleep(5 * attempt)
    return None


def discover_districts(direction_url):
    html = fetch_html(direction_url)
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    districts = {}
    for a in soup.select("a[href]"):
        href = a["href"]
        full = urljoin(BASE_URL, href)
        if "/حي-" not in full and "حي" not in full:
            continue
        if not full.startswith(direction_url + "/"):
            continue
        tail = full[len(direction_url) + 1:]
        if "/" in tail or re.search(r"-\d{4,}$", tail):
            continue
        last_segment = full.rstrip("/").split("/")[-1]
        if last_segment.isdigit():
            continue
        districts[full] = a.get_text(strip=True)
    return districts


def collect_ids_from_page(url):
    html = fetch_html(url)
    if not html:
        return set()
    soup = BeautifulSoup(html, "html.parser")
    ids = set()
    for a in soup.select("a[href]"):
        href = a["href"]
        full = urljoin(BASE_URL, href)
        match = re.search(r"-(\d{5,})/?$", full)
        if match:
            ids.add(match.group(1))
    return ids


def main():
    if len(sys.argv) < 3:
        print("الاستخدام: python crawl_active_ids_for_type.py <نوع-slug مثل فلل-للبيع> <اسم-مختصر مثل villa>")
        sys.exit(1)

    property_type_slug = sys.argv[1]
    type_key = sys.argv[2]

    all_ids = set()
    for region in REGIONS:
        direction_url = f"{BASE_URL}/{property_type_slug}/الرياض/{region}"
        print(f"=== {region} ===")
        districts = discover_districts(direction_url)
        print(f"  لقينا {len(districts)} حي")

        targets = list(districts.keys()) if districts else [direction_url]
        for district_url in targets:
            for page_num in range(1, MAX_PAGES_PER_DISTRICT + 1):
                page_url = district_url if page_num == 1 else f"{district_url}/{page_num}"
                ids = collect_ids_from_page(page_url)
                if not ids:
                    break
                all_ids.update(ids)
                time.sleep(1.5)

    print(f"\nإجمالي IDs نشطة لنوع {type_key}: {len(all_ids)}")

    output_path = f"data/active_ids_{type_key}_today.csv"
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["listing_id"])
        for lid in sorted(all_ids):
            writer.writerow([lid])
    print(f"تم الحفظ: {output_path}")


if __name__ == "__main__":
    main()
