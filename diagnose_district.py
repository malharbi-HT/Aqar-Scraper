"""
سكربت تشخيصي -- يمسح حي واحد بالتفصيل، صفحة صفحة، ويطبع بالضبط كم رابط لقى
بكل صفحة ومتى توقف ولیش. يفيدنا نفهم السبب الحقيقي لنقص التغطية بأحياء
معينة (زي حي السليمانية) بدل التخمين.
"""

import requests
from bs4 import BeautifulSoup
import re
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.8",
}

# غيّر هذا الرابط لأي حي تبي تشخّصه
DISTRICT_URL = "https://sa.aqar.fm/شقق-للبيع/الرياض/شرق-الرياض/حي-الرمال"
MAX_PAGES = 30


def fetch_html(url):
    for attempt in range(1, 6):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.text, resp.status_code
        except requests.RequestException as e:
            print(f"    محاولة {attempt} فشلت: {e}")
            time.sleep(5 * attempt)
    return None, None


def count_listing_links(html):
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.select("a[href]"):
        href = a["href"]
        if re.search(r"-\d{5,}/?$", href):
            links.add(href)
    return links


def main():
    print(f"تشخيص: {DISTRICT_URL}\n")
    all_links = set()
    consecutive_empty = 0

    for page_num in range(1, MAX_PAGES + 1):
        page_url = DISTRICT_URL if page_num == 1 else f"{DISTRICT_URL}/{page_num}"
        html, status = fetch_html(page_url)

        if html is None:
            print(f"صفحة {page_num}: فشل الجلب نهائيًا (status={status})")
            continue

        links = count_listing_links(html)
        new_links = links - all_links
        all_links.update(links)

        print(f"صفحة {page_num}: status={status} | روابط بالصفحة={len(links)} | جديد={len(new_links)} | تراكمي={len(all_links)}")

        if not links:
            consecutive_empty += 1
            print(f"  ⚠️  صفحة فاضية (رقم {consecutive_empty} متتالية)")
            if consecutive_empty >= 2:
                print(f"  توقفنا هنا (صفحتين فاضيتين متتاليتين)")
                break
        else:
            consecutive_empty = 0

        time.sleep(1.5)

    print(f"\nالإجمالي النهائي: {len(all_links)} رابط فريد")


if __name__ == "__main__":
    main()
