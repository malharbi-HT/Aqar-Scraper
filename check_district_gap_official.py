"""
يجيب العدد الرسمي لكل حي **كما هو مكتوب بصفحة الموقع نفسها** (مثل "حي النرجس (656)")،
ويقارنه بعدد الإعلانات اللي سحبناها فعليًا لنفس الحي -- بدون أي ملف مرجعي خارجي،
المصدر هو الموقع مباشرة.
"""

import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import os
import time
from urllib.parse import urljoin, unquote

BASE_URL = "https://sa.aqar.fm"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ACTIVE_IDS_PATH = os.path.join(DATA_DIR, "active_ids_today.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "district_official_vs_actual.csv")

DIRECTIONS = {
    "شمال الرياض": "https://sa.aqar.fm/شقق-للبيع/الرياض/شمال-الرياض",
    "شرق الرياض": "https://sa.aqar.fm/شقق-للبيع/الرياض/شرق-الرياض",
    "غرب الرياض": "https://sa.aqar.fm/شقق-للبيع/الرياض/غرب-الرياض",
    "جنوب الرياض": "https://sa.aqar.fm/شقق-للبيع/الرياض/جنوب-الرياض",
    "وسط الرياض": "https://sa.aqar.fm/شقق-للبيع/الرياض/وسط-الرياض",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.8",
}

COUNT_PATTERN = re.compile(r"\(([\d,]+)\)\s*$")


def fetch_html(url):
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"  محاولة {attempt} فشلت لـ {url}: {e}")
            time.sleep(5)
    return None


def discover_districts_with_counts(direction_url):
    """يرجع قاموس: اسم الحي -> (رابطه، العدد الرسمي المكتوب بالموقع)"""
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

        text = a.get_text(strip=True)
        match = COUNT_PATTERN.search(text)
        if not match:
            continue  # ما فيه رقم مذكور، نتخطاه
        official_count = int(match.group(1).replace(",", ""))
        district_name = COUNT_PATTERN.sub("", text).strip()
        districts[district_name] = official_count

    return districts


def parse_district_from_url(url):
    path = unquote(str(url).replace(BASE_URL, "")).strip("/")
    parts = path.split("/")
    if len(parts) > 3 and parts[3].startswith("حي"):
        return parts[3].replace("-", " ")
    return None


def main():
    if not os.path.exists(ACTIVE_IDS_PATH):
        print(f"تحذير: ما لقيت {ACTIVE_IDS_PATH} -- شغّل crawl_active_ids.py أول")
        return

    active = pd.read_csv(ACTIVE_IDS_PATH, encoding="utf-8-sig")
    active["district"] = active["url"].apply(parse_district_from_url)
    our_counts = active["district"].value_counts().to_dict()

    all_rows = []
    for direction_name, direction_url in DIRECTIONS.items():
        print(f"=== {direction_name} ===")
        districts = discover_districts_with_counts(direction_url)
        print(f"  لقينا {len(districts)} حي بأرقام رسمية مذكورة")

        for district_name, official_count in districts.items():
            our_count = our_counts.get(district_name, 0)
            diff = our_count - official_count
            all_rows.append({
                "المنطقة": direction_name,
                "الحي": district_name,
                "العدد_الرسمي_بالموقع": official_count,
                "عندنا": our_count,
                "الفرق": diff,
            })
        time.sleep(1)

    report = pd.DataFrame(all_rows).sort_values("الفرق")
    total_official = report["العدد_الرسمي_بالموقع"].sum()
    total_ours = report["عندنا"].sum()

    print(f"\nإجمالي رسمي (من الأحياء اللي فيها رقم مذكور): {total_official}")
    print(f"إجمالي عندنا لنفس الأحياء: {total_ours}")
    print(f"الفرق: {total_official - total_ours}")

    print(f"\n--- أكثر 15 حي ناقص ---")
    print(report[report["الفرق"] < 0].head(15).to_string(index=False))

    report.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nتم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
