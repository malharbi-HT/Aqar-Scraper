"""
يكتشف كل الأحياء الفرعية لنوع عقار معيّن (فلل/أدوار/أراضي/عمائر/مكاتب) عبر
كل المناطق الخمسة، ويطبع النتيجة بصيغة JSON مضغوطة (سطر واحد) -- يُستخدم هذا
الناتج مباشرة كمصفوفة GitHub Actions ديناميكية (كل حي = تشغيلة منفصلة).

الاستخدام:
    python discover_districts_for_type.py فلل-للبيع
"""

import requests
from bs4 import BeautifulSoup
import re
import sys
import json
import time
from urllib.parse import urljoin

BASE_URL = "https://sa.aqar.fm"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.8",
}

REGIONS = ["شمال-الرياض", "شرق-الرياض", "غرب-الرياض", "جنوب-الرياض", "وسط-الرياض"]


def fetch_html(url):
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"  محاولة {attempt} فشلت لـ {url}: {e}", file=sys.stderr)
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
        districts[full] = a.get_text(strip=True)

    return districts


def main():
    if len(sys.argv) < 2:
        print("الاستخدام: python discover_districts_for_type.py <نوع-العقار مثل فلل-للبيع>", file=sys.stderr)
        sys.exit(1)

    property_type_slug = sys.argv[1]
    all_districts = []

    for region in REGIONS:
        direction_url = f"{BASE_URL}/{property_type_slug}/الرياض/{region}"
        districts = discover_districts(direction_url)
        print(f"{region}: لقينا {len(districts)} حي", file=sys.stderr)

        for url, name in districts.items():
            all_districts.append({"url": url, "name": name, "region": region})

    # لو ما لقينا ولا حي (خلل مؤقت)، نرجع للمناطق كاملة كخطة بديلة
    if not all_districts:
        print("تحذير: ما لقينا أي حي، نرجع للمناطق كاملة كخطة بديلة", file=sys.stderr)
        all_districts = [
            {"url": f"{BASE_URL}/{property_type_slug}/الرياض/{r}", "name": r, "region": r}
            for r in REGIONS
        ]

    print(f"الإجمالي: {len(all_districts)} حي عبر كل المناطق", file=sys.stderr)
    # الناتج الفعلي (JSON مضغوط بسطر واحد) يطلع بـ stdout عشان GitHub يلتقطه بسهولة
    print(json.dumps(all_districts, ensure_ascii=False))


if __name__ == "__main__":
    main()
