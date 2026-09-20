"""
سكربت سحب كل أنواع العقارات للبيع بمكة المكرمة -- مبني بالضبط على نفس
منطق سكربت الدور الحقيقي المُثبت بالمشروع (scraper_floor.py)، لأن هذا هو
المنطق اللي فعليًا يشتغل مع aqar.fm (استخراج JSON مضمّن بالصفحة عبر آلية
Next.js RSC، مو تحليل HTML مرئي).

الفرق عن الرياض: مكة المكرمة ما فيها تقسيم مناطق (شمال/شرق/غرب...)،
فنستخدم صفحة المدينة نفسها كمكافئ لصفحة "المنطقة" (direction_url) اللي
تتوقعها دالة discover_districts -- تشتغل صح لأنها بس تدوّر على روابط
تبدأ بنفس الرابط + "/".
"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import time
import re
import os
from urllib.parse import urljoin, unquote

BASE_URL = "https://sa.aqar.fm"
CITY_SLUG = "مكة-المكرمة"

# كل الأنواع المؤكدة (سلاج الرابط، التسمية العربية)
import sys

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

TYPE_ARG = None
CHUNK_ARG = None  # صيغة "0/3" أو "1/3" أو "2/3" -- يقسّم الأحياء المكتشفة لأجزاء متوازية
if len(sys.argv) > 1:
    TYPE_ARG = sys.argv[1]
    matching = [t for t in PROPERTY_TYPES if t[0] == TYPE_ARG]
    if not matching:
        print(f"خطأ: نوع غير معروف '{TYPE_ARG}'. الأنواع المتاحة: {[t[0] for t in PROPERTY_TYPES]}")
        sys.exit(1)
    PROPERTY_TYPES = matching
    print(f"تشغيل مقتصر على نوع: {TYPE_ARG}")

if len(sys.argv) > 2 and sys.argv[2]:
    CHUNK_ARG = sys.argv[2]
    print(f"تشغيل مقتصر على جزء: {CHUNK_ARG}")

MAX_PAGES_PER_CATEGORY = 200
MAX_LISTINGS_PER_RUN = 600

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
OUTPUT_CSV = os.path.join(DATA_DIR, "listings_sale_mecca_all_types.csv")
if TYPE_ARG:
    safe_type = TYPE_ARG.replace("-", "_")
    if CHUNK_ARG:
        safe_chunk = CHUNK_ARG.replace("/", "_")
        OUTPUT_CSV = os.path.join(DATA_DIR, "mecca_by_type", f"listings_mecca_{safe_type}_{safe_chunk}.csv")
    else:
        OUTPUT_CSV = os.path.join(DATA_DIR, "mecca_by_type", f"listings_mecca_{safe_type}.csv")

CSV_FIELDS = [
    "listing_id", "url", "title", "price", "area_sqm",
    "rooms", "bathrooms", "livings", "age_years", "district", "city", "direction",
    "description", "latitude", "longitude", "images", "images_count",
    "advertiser_name", "advertiser_company", "advertiser_type",
    "created_at", "published_at", "last_update", "views", "date_scraped",
    "published", "price_text", "price_was_missing", "property_type",
]

IMAGE_BASE_URL = "https://images.aqar.fm/webp/750x0/props/"


def is_forbidden(path: str) -> bool:
    return any(path.startswith(p) for p in FORBIDDEN_PATH_PREFIXES)


def parse_city_direction_from_url(url):
    path = unquote(url.replace(BASE_URL, "")).strip("/")
    parts = path.split("/")
    city = parts[1].replace("-", " ") if len(parts) > 1 else None
    direction = parts[2].replace("-", " ") if len(parts) > 2 else None
    return city, direction


def extract_listing_id(url: str) -> str:
    match = re.search(r"-(\d+)/?$", url)
    return match.group(1) if match else url


def get_soup(url: str):
    last_error = None
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            last_error = e
            if attempt < 3:
                time.sleep(3 * attempt)
    raise last_error


NEXT_F_PATTERN = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', re.DOTALL)


def _unescape_js_string(raw):
    return json.loads('"' + raw + '"')


def extract_rsc_text(html):
    parts = []
    for m in NEXT_F_PATTERN.finditer(html):
        try:
            parts.append(_unescape_js_string(m.group(1)))
        except (json.JSONDecodeError, TypeError):
            continue
    return "".join(parts)


def resolve_text_reference(rsc_text, ref):
    m = re.match(r"^\$(\d+)$", ref or "")
    if not m:
        return ref
    chunk_id = m.group(1)
    pattern = re.compile(
        (r"(?:^|\n)" + re.escape(chunk_id) + r":T([0-9a-fA-F]+),").encode("utf-8"),
        re.MULTILINE,
    )
    full_bytes = rsc_text.encode("utf-8")
    match = pattern.search(full_bytes)
    if not match:
        return None
    length = int(match.group(1), 16)
    start = match.end()
    text_bytes = full_bytes[start:start + length]
    try:
        return text_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _extract_balanced_from(text, start):
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    i = start
    while i < len(text):
        c = text[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        i += 1
    return None


def extract_listing_json(html):
    rsc_text = extract_rsc_text(html)
    if not rsc_text:
        return None, ""

    search_from = 0
    while True:
        idx = rsc_text.find('"listing":{', search_from)
        if idx == -1:
            return None, rsc_text
        start = rsc_text.find("{", idx)
        candidate = _extract_balanced_from(rsc_text, start)
        if candidate:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and (
                    "price" in parsed or "imgs" in parsed or "rega_total_price" in parsed
                ):
                    return parsed, rsc_text
            except json.JSONDecodeError:
                pass
        search_from = idx + 1


def collect_listing_links_from_list_page(url: str):
    soup = get_soup(url)
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


def _fmt_timestamp(ts):
    if not ts:
        return None
    try:
        return time.strftime("%Y-%m-%d", time.localtime(int(ts)))
    except (ValueError, TypeError):
        return None


def scrape_listing_detail(url, type_label):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    html = resp.text

    data = {
        "listing_id": extract_listing_id(url),
        "url": url,
        "title": None, "price": None, "area_sqm": None,
        "rooms": None, "bathrooms": None, "livings": None, "age_years": None,
        "district": None, "city": None, "direction": None,
        "description": None, "latitude": None, "longitude": None,
        "images": None, "images_count": None,
        "advertiser_name": None, "advertiser_company": None, "advertiser_type": None,
        "created_at": None, "published_at": None, "last_update": None,
        "views": None, "date_scraped": time.strftime("%Y-%m-%d"),
        "property_type": type_label,
    }

    listing, rsc_text = extract_listing_json(html)

    if listing:
        data["title"] = listing.get("title")
        data["price"] = listing.get("price") or listing.get("rega_total_price")
        data["published"] = listing.get("published")
        data["price_text"] = listing.get("price_text")
        data["price_was_missing"] = listing.get("price") is None
        data["area_sqm"] = listing.get("area")
        data["rooms"] = listing.get("beds")
        data["bathrooms"] = listing.get("wc")
        data["livings"] = listing.get("livings")
        data["age_years"] = listing.get("age")
        data["district"] = listing.get("district")
        content = listing.get("content")
        if isinstance(content, str) and content.startswith("$"):
            content = resolve_text_reference(rsc_text, content)
        data["description"] = content

        loc = listing.get("location")
        if isinstance(loc, dict):
            data["latitude"] = loc.get("lat")
            data["longitude"] = loc.get("lng")

        imgs = listing.get("imgs") or []
        if isinstance(imgs, list) and imgs:
            full_urls = [IMAGE_BASE_URL + im for im in imgs if isinstance(im, str) and im]
            if full_urls:
                data["images"] = " | ".join(full_urls)
                data["images_count"] = len(full_urls)

        user = listing.get("user")
        if isinstance(user, dict):
            data["advertiser_name"] = user.get("name")
            data["advertiser_company"] = user.get("company_name")
            data["advertiser_type"] = user.get("type")

        data["created_at"] = _fmt_timestamp(listing.get("create_time"))
        data["published_at"] = _fmt_timestamp(listing.get("published_at"))
        data["last_update"] = _fmt_timestamp(listing.get("last_update"))
        data["views"] = listing.get("views")

    data["city"], data["direction"] = parse_city_direction_from_url(url)

    if not listing:
        soup = BeautifulSoup(html, "html.parser")
        og_title = soup.find("meta", property="og:title")
        if og_title:
            data["title"] = og_title.get("content")
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            data["description"] = og_desc.get("content")
        og_image = soup.find("meta", property="og:image")
        if og_image:
            data["images"] = og_image.get("content")
            data["images_count"] = 1

    return data


def discover_districts(direction_url):
    """يجيب كل روابط الأحياء المذكورة بصفحة المدينة (بدل صفحة المنطقة --
    مكة المكرمة ما فيها تقسيم مناطق، فصفحة المدينة نفسها تلعب نفس الدور)"""
    try:
        soup = get_soup(direction_url)
    except Exception as e:
        print(f"فشل جلب صفحة {direction_url}: {e}")
        return {}

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


def load_existing_ids():
    if not os.path.exists(OUTPUT_CSV):
        return set()
    with open(OUTPUT_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return {row["listing_id"] for row in reader}


def open_csv_writer():
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    file_exists = os.path.exists(OUTPUT_CSV)
    f = open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
    if not file_exists:
        writer.writeheader()
        f.flush()
    return f, writer


def main():
    existing_ids = load_existing_ids()
    print(f"عدد الإعلانات المحفوظة مسبقًا: {len(existing_ids)}")

    all_links_with_type = {}   # url -> type_label

    for type_slug, type_label in PROPERTY_TYPES:
        city_url = f"{BASE_URL}/{type_slug}/{CITY_SLUG}"
        print(f"\n{'='*50}\nنوع العقار: {type_label} ({type_slug})\n{'='*50}")

        enough_found = False  # علم نوقف بيه الاكتشاف فورًا بمجرد ما نلقط كفاية

        districts = discover_districts(city_url)
        print(f"لقينا {len(districts)} حي")
        if not districts:
            print(f"  ما لقينا أي حي لنوع {type_label} -- تخطّينا")
            continue

        # تقسيم الأحياء لأجزاء متوازية (لو CHUNK_ARG محدد) -- ترتيب ثابت
        # (بالاسم) عشان نفس الحي يروح لنفس الجزء دائمًا بكل تشغيلة
        if CHUNK_ARG:
            chunk_index, chunk_total = map(int, CHUNK_ARG.split("/"))
            sorted_items = sorted(districts.items(), key=lambda x: x[1])
            districts = dict(
                item for i, item in enumerate(sorted_items) if i % chunk_total == chunk_index
            )
            print(f"  بعد التقسيم (جزء {chunk_index}/{chunk_total}): {len(districts)} حي")

        for district_url, district_name in districts.items():
            if enough_found:
                break
            print(f"  --- حي: {district_name} ---")
            for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
                page_url = district_url if page_num == 1 else f"{district_url}/{page_num}"
                try:
                    links = collect_listing_links_from_list_page(page_url)
                except requests.RequestException as e:
                    print(f"    تخطي {page_url}: {e}")
                    continue
                if not links:
                    print(f"    وصلنا آخر صفحة عند صفحة {page_num - 1}")
                    break

                new_on_page = [l for l in links if extract_listing_id(l) not in existing_ids]
                print(f"    صفحة {page_num}: لقيت {len(links)} رابط ({len(new_on_page)} جديد)")
                for link in links:
                    all_links_with_type[link] = type_label

                total_new_so_far = sum(
                    1 for u in all_links_with_type if extract_listing_id(u) not in existing_ids
                )
                if total_new_so_far >= int(MAX_LISTINGS_PER_RUN * 1.5):
                    print(f"    لقينا {total_new_so_far} رابط جديد -- كافي لهالتشغيلة، نوقف الاكتشاف")
                    enough_found = True
                    break

                time.sleep(2)
            time.sleep(2)

    new_links = [(url, t) for url, t in all_links_with_type.items() if extract_listing_id(url) not in existing_ids]
    total_pending = len(new_links)
    if total_pending > MAX_LISTINGS_PER_RUN:
        print(f"تنبيه: {total_pending} رابط جديد، بس نقتصر على {MAX_LISTINGS_PER_RUN} بهالتشغيلة")
        print(f"الباقي ({total_pending - MAX_LISTINGS_PER_RUN}) بيكمل تلقائيًا بالتشغيلة الجاية")
        new_links = new_links[:MAX_LISTINGS_PER_RUN]
    print(f"روابط للسحب بهالتشغيلة: {len(new_links)}")

    f, writer = open_csv_writer()
    saved_count = 0
    try:
        for link, type_label in new_links:
            try:
                row = scrape_listing_detail(link, type_label)
                writer.writerow(row)
                f.flush()
                saved_count += 1
                print(f"تم ({saved_count}/{len(new_links)}):", row["listing_id"], row.get("title"))
            except requests.RequestException as e:
                print(f"فشل سحب {link}: {e}")
            time.sleep(2)
    finally:
        f.close()

    if saved_count:
        print(f"تمت إضافة {saved_count} إعلان جديد إلى {OUTPUT_CSV}")
    else:
        print("لا توجد إعلانات جديدة.")


if __name__ == "__main__":
    main()
