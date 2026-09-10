"""
سحب شقق للبيع بالمدينة المنورة -- سكربت جديد كامل، مستقل عن سكربتات الرياض.

الفرق عن الرياض: المدينة المنورة ما فيها تقسيم مناطق (شمال/شرق/جنوب...)،
الرابط يروح مباشرة من المدينة للحي:
    الرياض:  aqar.fm/شقق-للبيع/الرياض/شمال-الرياض/حي-X
    المدينة: aqar.fm/شقق-للبيع/المدينة-المنورة/حي-X

اكتشاف الأحياء: صفحة القائمة الرئيسية للمدينة تعرض كل الأحياء مع عدد
إعلاناتها بين قوسين مباشرة -- زي [حي الرانوناء (74)] -- نستخدمها للاكتشاف
الكامل بدل تخمين الأسماء.

الاستخراج: صفحة القائمة (مو صفحة التفاصيل) تعرض بيانات كافية لكل إعلان
(سعر، مساحة، غرف، حمامات، صالات، الوصف الكامل) -- نكتفي بمرحلة وحدة
(صفحات القائمة بس)، بدون زيارة كل إعلان تفاصيل منفصلة (أسرع بكثير).
"""

import requests
from bs4 import BeautifulSoup
import re
import csv
import os
import time
from urllib.parse import urljoin, unquote

BASE_URL = "https://sa.aqar.fm"
CATEGORY_URL = f"{BASE_URL}/شقق-للبيع/المدينة-المنورة"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "listings_sale_medina.csv")

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


def discover_districts():
    """يجيب كل أحياء المدينة المنورة من صفحة الفئة الرئيسية -- الرابط
    والاسم وعدد الإعلانات (بين قوسين بجانب اسم الحي مباشرة)"""
    html = fetch_html(CATEGORY_URL)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    districts = {}
    for a in soup.select("a[href]"):
        href = a["href"]
        full = urljoin(BASE_URL, href)
        if "/المدينة-المنورة/حي-" not in full and "حي-" not in full.split("المدينة-المنورة/")[-1] if "المدينة-المنورة/" in full else True:
            pass
        if "المدينة-المنورة/حي" not in full:
            continue
        # نستبعد أي رابط فيه صفحة ترقيم أو فلتر إضافي (يبدأ بالحي مباشرة وينتهي عنده)
        tail = full.split("المدينة-المنورة/")[-1]
        if "/" in tail:
            continue
        text = a.get_text(strip=True)
        if full not in districts:
            districts[full] = text
    return list(districts.items())


def parse_listing_card(card_text, card_url):
    """يستخرج بيانات إعلان وحد من نص كارت القائمة -- نمط aqar.fm الثابت:
    'السعر § - المساحةم² - غرف - حمامات - صالات' يتبعه نص الوصف الكامل"""
    listing_id_match = re.search(r"-(\d{6,})/?$", card_url)
    listing_id = listing_id_match.group(1) if listing_id_match else None

    price_match = re.search(r"([\d,]+)\s*§", card_text)
    area_match = re.search(r"-\s*([\d,]+)\s*م²", card_text)
    # النمط: بعد المساحة، أرقام مفصولة بشرطات (غرف - حمامات - صالات)، متغيرة العدد
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

    # الوصف: كل شي بعد نمط الأرقام لين قبل اسم الحي المكرر بآخر الكارت
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
        "district": district,
        "city": "المدينة المنورة",
        "price": price_match.group(1).replace(",", "") if price_match else None,
        "area_sqm": area_match.group(1).replace(",", "") if area_match else None,
        "rooms": rooms,
        "bathrooms": bathrooms,
        "livings": livings,
        "description": description,
    }


def scrape_district(district_url, district_name):
    """يسحب كل صفحات حي معيّن، صفحة صفحة، لين ما فيه نتائج جديدة"""
    all_listings = []
    for page_num in range(1, MAX_PAGES_PER_DISTRICT + 1):
        page_url = district_url if page_num == 1 else f"{district_url}/{page_num}"
        html = fetch_html(page_url)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")
        # كل رابط إعلان فردي (ينتهي برقم طويل، وموجود جوا رابط الحي نفسه)
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
            # نلقط جزء النص المرتبط بهالرابط تقريبيًا -- نبحث عن نمط قريب منه بالنص الكامل
            listing_id_match = re.search(r"-(\d{6,})/?$", link)
            if not listing_id_match:
                continue
            lid = listing_id_match.group(1)
            # نقص نافذة نص حوالين ذكر الرقم (تقريبي، كافٍ لالتقاط الكارت)
            idx = page_text.find(lid)
            window = page_text[max(0, idx - 800):idx + 200] if idx >= 0 else ""
            parsed = parse_listing_card(window, link)
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
    print("=== اكتشاف أحياء المدينة المنورة ===")
    districts = discover_districts()
    print(f"لقينا {len(districts)} حي")

    all_results = []
    for district_url, district_name in districts:
        print(f"\n=== {district_name} ===")
        listings = scrape_district(district_url, district_name)
        print(f"  إجمالي: {len(listings)} إعلان")
        all_results.extend(listings)

    print(f"\nإجمالي كل الأحياء: {len(all_results)} إعلان")

    if all_results:
        fieldnames = list(all_results[0].keys())
        with open(OUTPUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_results)
        print(f"تم الحفظ: {OUTPUT_PATH}")
    else:
        print("ما لقينا أي نتائج -- تحقق من بنية الصفحة (يحتمل تغيّرت)")


if __name__ == "__main__":
    main()
