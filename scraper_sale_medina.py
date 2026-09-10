"""
سحب كل أنواع العقارات للبيع بالمدينة المنورة -- سكربت جديد كامل، مستقل
عن سكربتات الرياض.

الأنواع المغطّاة (روابط مؤكدة بالبحث المباشر):
شقق، أراضي، دور، فلل، عمائر، مكاتب، محلات، مستودعات، مصانع
("ورش" مالها تصنيف مستقل بالموقع -- تندرج تحت محلات أو مصانع، استبعدناها)

الفرق عن الرياض: المدينة المنورة ما فيها تقسيم مناطق (شمال/شرق/جنوب...)،
الرابط يروح مباشرة من المدينة للحي:
    الرياض:  aqar.fm/[نوع]/الرياض/شمال-الرياض/حي-X
    المدينة: aqar.fm/[نوع]/المدينة-المنورة/حي-X

اكتشاف الأحياء: صفحة القائمة الرئيسية لكل نوع تعرض كل الأحياء مع عدد
إعلاناتها بين قوسين مباشرة -- زي [حي الرانوناء (74)] -- نستخدمها للاكتشاف
الكامل بدل تخمين الأسماء.

الاستخراج: صفحة القائمة (مو صفحة التفاصيل) تعرض بيانات كافية لكل إعلان
(سعر، مساحة، غرف، حمامات، صالات، الوصف الكامل) -- نكتفي بمرحلة وحدة.
"""

import requests
from bs4 import BeautifulSoup
import re
import csv
import os
import time
from urllib.parse import urljoin

BASE_URL = "https://sa.aqar.fm"
CITY_SLUG = "المدينة-المنورة"
CITY_NAME = "المدينة المنورة"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "listings_sale_medina_all_types.csv")

# كل الأنواع المؤكدة (السلاج بالرابط، التسمية العربية)
PROPERTY_TYPES = [
    ("شقق-للبيع", "شقة"),
    ("أراضي-للبيع", "أرض"),
    ("دور-للبيع", "دور"),
    ("فلل-للبيع", "فيلا"),
    ("عمائر-للبيع", "عمارة"),
    ("مكاتب-للبيع", "مكتب"),
    ("محلات-للبيع", "محل"),
    ("مستودعات-للبيع", "مستودع"),
    ("مصانع-للبيع", "مصنع"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.8",
}
MAX_PAGES_PER_DISTRICT = 100
REQUEST_DELAY = 1.5


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


def discover_districts(category_url, type_slug):
    """يجيب كل أحياء المدينة المنورة لنوع عقار معيّن من صفحة الفئة الرئيسية"""
    print(f"  جلب: {category_url}")
    html = fetch_html(category_url)
    if not html:
        print("  فشل جلب صفحة الفئة الرئيسية")
        return []

    soup = BeautifulSoup(html, "html.parser")
    all_links = soup.select("a[href]")
    print(f"  إجمالي الروابط بالصفحة: {len(all_links)}")

    districts = {}
    for a in all_links:
        href = a["href"]
        full = urljoin(BASE_URL, href)
        if f"{CITY_SLUG}/حي" not in full:
            continue
        tail_after_district = re.sub(rf"^.*?{CITY_SLUG}/(حي-[^/]+).*$", r"\1", full)
        expected_full = f"{BASE_URL}/{type_slug}/{CITY_SLUG}/{tail_after_district}"
        if full != expected_full:
            continue
        text = a.get_text(strip=True)
        if full not in districts:
            districts[full] = text

    print(f"  أحياء صافية: {len(districts)}")
    return list(districts.items())


def parse_listing_card(card_text, card_url, type_label):
    """يستخرج بيانات إعلان وحد من نص كارت القائمة -- نمط aqar.fm الثابت:
    'السعر § - المساحةم² - غرف - حمامات - صالات' يتبعه نص الوصف الكامل"""
    listing_id_match = re.search(r"-(\d{6,})/?$", card_url)
    listing_id = listing_id_match.group(1) if listing_id_match else None

    price_match = re.search(r"([\d,]+)\s*§", card_text)
    area_match = re.search(r"-\s*([\d,]+)\s*م²", card_text)
    nums_after_area = re.search(r"م²\s*((?:\s*-\s*\d+)+)", card_text)
    rooms = bathrooms = livings = None
    if nums_after_area:
        parts = [p.strip() for p in nums_after_area.group(1).split("-") if p.strip()]
        if len(parts) >= 1:
            rooms = parts[0]
        if len(parts) >= 2:
            bathrooms = parts[1]
        if len(parts) >= 3:
            livings = parts[2]

    desc_start = nums_after_area.end() if nums_after_area else (area_match.end() if area_match else 0)
    description = card_text[desc_start:].strip()

    district_match = re.search(r"حي\s+([^\s,]+(?:\s+[^\s,]+){0,3}),\s*مدينة", card_text)
    district = f"حي {district_match.group(1)}" if district_match else None

    title_match = re.search(r"^(.*?منطقة المدينة المنورة)", card_text)
    title = title_match.group(1).strip() if title_match else card_text[:100]

    return {
        "listing_id": listing_id,
        "url": card_url,
        "title": title,
        "نوع_العقار": type_label,
        "district": district,
        "city": CITY_NAME,
        "price": price_match.group(1).replace(",", "") if price_match else None,
        "area_sqm": area_match.group(1).replace(",", "") if area_match else None,
        "rooms": rooms,
        "bathrooms": bathrooms,
        "livings": livings,
        "description": description,
    }


def scrape_district(district_url, district_name, type_label):
    """يسحب كل صفحات حي معيّن لنوع عقار معيّن، صفحة صفحة"""
    all_listings = []
    for page_num in range(1, MAX_PAGES_PER_DISTRICT + 1):
        page_url = district_url if page_num == 1 else f"{district_url}/{page_num}"
        html = fetch_html(page_url)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")
        listing_links = set()
        for a in soup.select("a[href]"):
            href = urljoin(BASE_URL, a["href"])
            if district_url in href and re.search(r"-\d{6,}/?$", href):
                listing_links.add(href)

        if not listing_links:
            break

        page_text = soup.get_text(separator=" ", strip=True)
        found_this_page = 0
        for link in listing_links:
            listing_id_match = re.search(r"-(\d{6,})/?$", link)
            if not listing_id_match:
                continue
            lid = listing_id_match.group(1)
            idx = page_text.find(lid)
            window = page_text[max(0, idx - 800):idx + 200] if idx >= 0 else ""
            parsed = parse_listing_card(window, link, type_label)
            parsed["district"] = parsed["district"] or district_name
            if parsed["price"] and parsed["listing_id"]:
                all_listings.append(parsed)
                found_this_page += 1

        print(f"    صفحة {page_num}: {found_this_page} إعلان")
        if found_this_page == 0:
            break
        time.sleep(REQUEST_DELAY)

    return all_listings


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    all_results = []

    for type_slug, type_label in PROPERTY_TYPES:
        category_url = f"{BASE_URL}/{type_slug}/{CITY_SLUG}"
        print(f"\n{'='*50}\nنوع العقار: {type_label} ({type_slug})\n{'='*50}")

        districts = discover_districts(category_url, type_slug)
        if not districts:
            print(f"  ما لقينا أحياء لنوع {type_label} -- تخطّينا")
            continue

        type_results = []
        for district_url, district_name in districts:
            print(f"  -- {district_name} --")
            listings = scrape_district(district_url, district_name, type_label)
            print(f"    إجمالي: {len(listings)} إعلان")
            type_results.extend(listings)

        print(f"إجمالي {type_label}: {len(type_results)} إعلان")
        all_results.extend(type_results)

    print(f"\n{'='*50}\nإجمالي كل الأنواع: {len(all_results)} إعلان\n{'='*50}")

    fieldnames = list(all_results[0].keys()) if all_results else [
        "listing_id", "url", "title", "نوع_العقار", "district", "city",
        "price", "area_sqm", "rooms", "bathrooms", "livings", "description",
    ]
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

    if all_results:
        print(f"تم الحفظ: {OUTPUT_PATH}")
        # ملخص بالعدد لكل نوع
        from collections import Counter
        counts = Counter(r["نوع_العقار"] for r in all_results)
        for type_label, count in counts.most_common():
            print(f"  {type_label}: {count}")
    else:
        print(f"تحذير: ما لقينا أي نتائج -- تم حفظ ملف فاضي: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
