"""
سكربت سحب بيانات العقارات من aqar.fm
- يسحب صفحات القوائم (listing pages) لاستخراج روابط الإعلانات
- يفتح كل إعلان ويحاول استخراج البيانات الكاملة (بما فيها الصور والإحداثيات)
  عبر قراءة الـ JSON المضمّن بالصفحة (__NEXT_DATA__) إن وجد، وإلا يرجع لـ HTML parsing
- يحفظ النتائج بملف CSV، ويتجنب تكرار الإعلانات (dedupe حسب رقم الإعلان الفريد)
"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import time
import re
import os
from urllib.parse import urljoin

BASE_URL = "https://sa.aqar.fm"

# ==== عدّل هذي القائمة حسب احتياجك (مدينة/نوع عقار/عدد صفحات) ====
LIST_PAGES = [
    "https://sa.aqar.fm/شقق-للبيع/الرياض",
]
MAX_PAGES_PER_CATEGORY = 5   # كم صفحة نسحب من كل تصنيف

# مسارات محظورة صراحة بـ robots.txt -- لازم نتجنبها دائمًا
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
OUTPUT_CSV = os.path.join(DATA_DIR, "listings.csv")

CSV_FIELDS = [
    "listing_id", "url", "title", "price", "area_sqm",
    "rooms", "bathrooms", "floor", "district", "city", "region",
    "description", "latitude", "longitude", "images", "date_scraped",
]


def is_forbidden(path: str) -> bool:
    return any(path.startswith(p) for p in FORBIDDEN_PATH_PREFIXES)


def extract_listing_id(url: str) -> str:
    """الرقم التعريفي دائمًا آخر أرقام بنهاية الرابط"""
    match = re.search(r"-(\d+)/?$", url)
    return match.group(1) if match else url


def get_soup(url: str):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def find_next_data(soup: BeautifulSoup):
    """يحاول يلقط بيانات JSON المضمّنة (Next.js). ترجع dict أو None."""
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except (json.JSONDecodeError, TypeError):
        return None


def deep_find_keys(obj, target_keys, found=None):
    """يبحث بعمق داخل JSON متداخل عن مفاتيح معينة (lat/lng/images...)."""
    if found is None:
        found = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = k.lower()
            if lk in target_keys and lk not in found:
                found[lk] = v
            deep_find_keys(v, target_keys, found)
    elif isinstance(obj, list):
        for item in obj:
            deep_find_keys(item, target_keys, found)
    return found


def collect_listing_links_from_list_page(url: str):
    """يسحب صفحة قائمة ويرجع روابط الإعلانات + بيانات أساسية سريعة"""
    soup = get_soup(url)
    links = set()
    for a in soup.select("a[href]"):
        href = a["href"]
        full = urljoin(BASE_URL, href)
        path = full.replace(BASE_URL, "")
        if is_forbidden(path):
            continue
        # روابط الإعلانات تنتهي برقم تعريفي طويل
        if re.search(r"-\d{5,}/?$", full):
            links.add(full)
    return links


def scrape_listing_detail(url: str) -> dict:
    """يفتح صفحة إعلان مفرد ويستخرج كل ما يقدر عليه"""
    soup = get_soup(url)
    data = {
        "listing_id": extract_listing_id(url),
        "url": url,
        "title": None, "price": None, "area_sqm": None,
        "rooms": None, "bathrooms": None, "floor": None,
        "district": None, "city": None, "region": None,
        "description": None, "latitude": None, "longitude": None,
        "images": None, "date_scraped": time.strftime("%Y-%m-%d"),
    }

    # --- محاولة 1: قراءة الـ JSON المضمّن (الأدق والأشمل لو موجود) ---
    next_data = find_next_data(soup)
    if next_data:
        found = deep_find_keys(
            next_data,
            {"lat", "latitude", "lng", "longitude", "images", "photos",
             "price", "area", "rooms", "bathrooms", "floor",
             "district", "city", "title", "description"},
        )
        data["latitude"] = found.get("lat") or found.get("latitude")
        data["longitude"] = found.get("lng") or found.get("longitude")
        imgs = found.get("images") or found.get("photos")
        if isinstance(imgs, list):
            # الصور ممكن تكون قائمة روابط أو قائمة dicts فيها url
            urls = []
            for im in imgs:
                if isinstance(im, str):
                    urls.append(im)
                elif isinstance(im, dict):
                    urls.append(im.get("url") or im.get("src") or "")
            data["images"] = " | ".join(u for u in urls if u)
        if found.get("price"):
            data["price"] = found.get("price")
        if found.get("area"):
            data["area_sqm"] = found.get("area")
        if found.get("title"):
            data["title"] = found.get("title")
        if found.get("description"):
            data["description"] = found.get("description")

    # --- محاولة 2 (احتياطية): وسوم meta / og تعطي عنوان ووصف على الأقل ---
    if not data["title"]:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            data["title"] = og_title.get("content")
    if not data["description"]:
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            data["description"] = og_desc.get("content")
    if not data["images"]:
        og_image = soup.find("meta", property="og:image")
        if og_image:
            data["images"] = og_image.get("content")

    return data


def load_existing_ids():
    if not os.path.exists(OUTPUT_CSV):
        return set()
    with open(OUTPUT_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return {row["listing_id"] for row in reader}


def append_rows(rows):
    os.makedirs(DATA_DIR, exist_ok=True)
    file_exists = os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def main():
    existing_ids = load_existing_ids()
    print(f"عدد الإعلانات المحفوظة مسبقًا: {len(existing_ids)}")

    all_links = set()
    for base in LIST_PAGES:
        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
            page_url = base if page_num == 1 else f"{base}/{page_num}"
            try:
                links = collect_listing_links_from_list_page(page_url)
            except requests.RequestException as e:
                print(f"تخطي {page_url}: {e}")
                continue
            if not links:
                break  # وصلنا آخر صفحة متاحة
            all_links.update(links)
            time.sleep(2)  # احترام السيرفر

    new_links = [l for l in all_links if extract_listing_id(l) not in existing_ids]
    print(f"روابط جديدة للسحب: {len(new_links)}")

    new_rows = []
    for link in new_links:
        try:
            row = scrape_listing_detail(link)
            new_rows.append(row)
            print("تم:", row["listing_id"], row.get("title"))
        except requests.RequestException as e:
            print(f"فشل سحب {link}: {e}")
        time.sleep(2)  # احترام السيرفر بين الطلبات

    if new_rows:
        append_rows(new_rows)
        print(f"تمت إضافة {len(new_rows)} إعلان جديد إلى {OUTPUT_CSV}")
    else:
        print("لا توجد إعلانات جديدة اليوم.")


if __name__ == "__main__":
    main()
