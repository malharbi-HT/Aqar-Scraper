import os
import re
import time
import random

import google.auth
import gspread
from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

MIN_DELAY = float(os.getenv("MIN_DELAY", "3"))
MAX_DELAY = float(os.getenv("MAX_DELAY", "7"))
PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "45000"))

# All real-estate tabs in your current workbook.
# Dashboard is intentionally excluded.
CITY_SHEETS = [
    "الطائف",
    "أبها",
    "خميس مشيط",
    "جازان",
    "القصيم",
    "الشرقية",
    "الرياض",
    "المدينة",
    "جدة",
    "مكة",
]


# ============================================================
# ARABIC DIGITS
# ============================================================

ARABIC_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789"
)


def normalize_digits(text):
    if text is None:
        return ""

    return str(text).translate(ARABIC_DIGITS)


# ============================================================
# PHONE HELPERS
# ============================================================

def normalize_phone(value):
    """
    Normalize Saudi mobile numbers into:
    05XXXXXXXX
    """

    if not value:
        return ""

    value = normalize_digits(value)

    digits = re.sub(r"\D", "", value)

    if digits.startswith("00966"):
        digits = digits[5:]

    elif digits.startswith("966"):
        digits = digits[3:]

    if len(digits) == 9 and digits.startswith("5"):
        digits = "0" + digits

    if re.fullmatch(r"05\d{8}", digits):
        return digits

    return ""


def extract_phone(text):
    if not text:
        return ""

    text = normalize_digits(text)

    patterns = [
        # +966551234567
        # +966 55 123 4567
        # 00966551234567
        r"(?:\+?966|00966)[\s\-\.]*5[\s\-\.]*\d{2}[\s\-\.]*\d{3}[\s\-\.]*\d{4}",

        # 055 123 4567
        # 055-123-4567
        r"05[\s\-\.]*\d{2}[\s\-\.]*\d{3}[\s\-\.]*\d{4}",

        # 0551234567
        r"\b05\d{8}\b",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text)

        for item in matches:
            phone = normalize_phone(item)

            if phone:
                return phone

    return ""


# ============================================================
# OWNER / BROKER
# ============================================================

def detect_owner_or_broker(text):
    if not text:
        return ""

    text = normalize_digits(text).lower()

    # Strongest signal: explicit Aqar advertiser type.
    owner_patterns = [
        r"صفة\s*المعلن\s*[:：]?\s*مالك",
        r"نوع\s*المعلن\s*[:：]?\s*مالك",
    ]

    broker_patterns = [
        r"صفة\s*المعلن\s*[:：]?\s*وسيط",
        r"صفة\s*المعلن\s*[:：]?\s*مسوق",
        r"نوع\s*المعلن\s*[:：]?\s*وسيط",
    ]

    for pattern in owner_patterns:
        if re.search(pattern, text):
            return "مالك"

    for pattern in broker_patterns:
        if re.search(pattern, text):
            return "وسيط"

    # Strong broker indicators.
    broker_keywords = [
        "وسيط عقاري",
        "وسيط ومسوق عقاري",
        "مسوق عقاري",
        "رخصة فال",
        "ترخيص فال",
        "رقم رخصة فال",
        "رقم عقد الوساطة",
        "عقد الوساطة",
        "مكتب عقاري",
        "شركة عقارية",
        "مؤسسة عقارية",
    ]

    for keyword in broker_keywords:
        if keyword in text:
            return "وسيط"

    # Strong owner indicators.
    owner_keywords = [
        "من المالك مباشرة",
        "مباشر من المالك",
        "المالك مباشرة",
        "مالك العقار",
        "أنا المالك",
        "انا المالك",
        "من المالك",
    ]

    for keyword in owner_keywords:
        if keyword in text:
            return "مالك"

    # Don't guess.
    return ""


# ============================================================
# TEL LINKS
# ============================================================

def phone_from_tel_links(page):
    try:
        links = page.locator('a[href^="tel:"]')

        for i in range(links.count()):
            href = links.nth(i).get_attribute("href")

            if not href:
                continue

            phone = extract_phone(href)

            if phone:
                return phone

    except Exception:
        pass

    return ""


# ============================================================
# CONTACT BUTTON
# ============================================================

def click_show_phone(page):
    """
    Try to reveal the advertiser number only if it was not
    already visible in the page content.
    """

    labels = [
        "إظهار رقم الاتصال",
        "إظهار الرقم",
        "عرض رقم الاتصال",
        "عرض الرقم",
        "رقم الاتصال",
        "اتصال",
        "اتصل",
    ]

    # First try exact visible text.
    for label in labels:
        try:
            locator = page.get_by_text(
                label,
                exact=True
            )

            count = locator.count()

            for i in range(min(count, 5)):
                item = locator.nth(i)

                try:
                    if not item.is_visible():
                        continue

                    href = item.get_attribute("href")

                    if href and href.startswith("tel:"):
                        return href

                    item.scroll_into_view_if_needed()

                    time.sleep(0.5)

                    item.click(timeout=5000)

                    time.sleep(2)

                    return True

                except Exception:
                    continue

        except Exception:
            continue

    # Then try common DOM selectors.
    selectors = [
        'button:has-text("إظهار رقم الاتصال")',
        'button:has-text("إظهار الرقم")',
        'button:has-text("عرض رقم الاتصال")',
        'button:has-text("اتصال")',
        'button:has-text("اتصل")',
        '[role="button"]:has-text("إظهار رقم الاتصال")',
        '[role="button"]:has-text("إظهار")',
        '[role="button"]:has-text("اتصال")',
        '[role="button"]:has-text("اتصل")',
        'a[href^="tel:"]',
    ]

    for selector in selectors:
        try:
            items = page.locator(selector)

            count = items.count()

            for i in range(min(count, 5)):
                item = items.nth(i)

                try:
                    if not item.is_visible():
                        continue

                    href = item.get_attribute("href")

                    if href and href.startswith("tel:"):
                        return href

                    item.scroll_into_view_if_needed()

                    time.sleep(0.5)

                    item.click(timeout=5000)

                    time.sleep(2)

                    return True

                except Exception:
                    continue

        except Exception:
            continue

    return False


# ============================================================
# PROCESS ONE Aqar LISTING
# ============================================================

def process_aqar_listing(page, url):
    result = {
        "phone": "",
        "owner_or_broker": "",
    }

    if not url or not str(url).startswith("http"):
        return result

    print()
    print("Opening:", url)

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

    except Exception as exc:
        print(
            "Page load warning:",
            exc
        )

    # Give dynamic content a chance to render.
    time.sleep(3)

    # --------------------------------------------------------
    # STEP 1:
    # Description + visible additional info + advertiser info
    # --------------------------------------------------------

    try:
        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=10000
        )

    except Exception:
        body_text = ""

    owner_type = detect_owner_or_broker(
        body_text
    )

    if owner_type:
        result["owner_or_broker"] = owner_type

    phone = extract_phone(
        body_text
    )

    if phone:
        print(
            "Phone found in visible page:",
            phone
        )

        result["phone"] = phone

        return result

    # --------------------------------------------------------
    # STEP 2:
    # Existing tel links
    # --------------------------------------------------------

    phone = phone_from_tel_links(
        page
    )

    if phone:
        print(
            "Phone found in tel link:",
            phone
        )

        result["phone"] = phone

        return result

    # --------------------------------------------------------
    # STEP 3:
    # Click contact / show phone
    # --------------------------------------------------------

    print(
        "No visible phone. Trying contact button..."
    )

    clicked = click_show_phone(
        page
    )

    if isinstance(clicked, str):
        phone = extract_phone(
            clicked
        )

        if phone:
            print(
                "Phone found from contact link:",
                phone
            )

            result["phone"] = phone

            return result

    if clicked:
        time.sleep(3)

        # Check tel links again.
        phone = phone_from_tel_links(
            page
        )

        if phone:
            print(
                "Phone found after click:",
                phone
            )

            result["phone"] = phone

            return result

        # Read page again after modal/reveal.
        try:
            updated_text = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

        except Exception:
            updated_text = ""

        phone = extract_phone(
            updated_text
        )

        if phone:
            print(
                "Phone revealed after click:",
                phone
            )

            result["phone"] = phone

        if not result["owner_or_broker"]:
            result["owner_or_broker"] = (
                detect_owner_or_broker(
                    updated_text
                )
            )

    if not result["phone"]:
        print("Phone not found.")

    if not result["owner_or_broker"]:
        print("Owner/broker could not be determined.")

    return result


# ============================================================
# GOOGLE AUTH
# ============================================================

def get_spreadsheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials, project_id = google.auth.default(
        scopes=scopes
    )

    print(
        "Authenticated to Google Cloud project:",
        project_id
    )

    client = gspread.authorize(
        credentials
    )

    spreadsheet = client.open_by_key(
        GOOGLE_SHEET_ID
    )

    print(
        "Google Sheet opened:",
        spreadsheet.title
    )

    return spreadsheet


# ============================================================
# COLUMN HELPERS
# ============================================================

def find_column(headers, choices):
    normalized = {}

    for index, header in enumerate(headers):
        if header is None:
            continue

        key = str(header).strip().lower()

        if not key:
            continue

        normalized[key] = index

    for choice in choices:
        key = str(choice).strip().lower()

        if key in normalized:
            return normalized[key]

    return None


def normalize_decision(value):
    value = str(
        value
    ).strip().upper()

    if value in [
        "PROCEED",
        "بروسيد",
    ]:
        return "PROCEED"

    if value in [
        "REVIEW",
        "ريفيو",
    ]:
        return "REVIEW"

    if value in [
        "REJECT",
        "ريجكت",
    ]:
        return "REJECT"

    return value


# ============================================================
# PREPARE A CITY TAB
# ============================================================

def inspect_worksheet(worksheet):
    all_rows = worksheet.get_all_values()

    if not all_rows:
        print(
            f"{worksheet.title}: empty - skipping."
        )

        return None

    headers = all_rows[0]
    data = all_rows[1:]

    url_index = find_column(
        headers,
        [
            "url",
            "listing_url",
            "property_url",
            "link",
            "رابط",
            "رابط العقار",
        ]
    )

    decision_index = find_column(
        headers,
        [
            "property_verdict",
            "decision",
            "initial_verdict",
            "verdict",
            "القرار",
        ]
    )

    phone_index = find_column(
        headers,
        [
            "phone",
        ]
    )

    owner_index = find_column(
        headers,
        [
            "owner_or_broker",
        ]
    )

    if url_index is None:
        print(
            f"{worksheet.title}: url column not found - skipping."
        )

        return None

    if decision_index is None:
        print(
            f"{worksheet.title}: property_verdict column not found - skipping."
        )

        return None

    # These already exist in your current workbook,
    # but this keeps the script safe if a tab is missing them.
    if phone_index is None:
        phone_index = len(headers)

        worksheet.update_cell(
            1,
            phone_index + 1,
            "phone"
        )

        headers.append(
            "phone"
        )

        print(
            f"{worksheet.title}: added phone column."
        )

    if owner_index is None:
        owner_index = len(headers)

        worksheet.update_cell(
            1,
            owner_index + 1,
            "owner_or_broker"
        )

        headers.append(
            "owner_or_broker"
        )

        print(
            f"{worksheet.title}: added owner_or_broker column."
        )

    return {
        "worksheet": worksheet,
        "headers": headers,
        "data": data,
        "url_index": url_index,
        "decision_index": decision_index,
        "phone_index": phone_index,
        "owner_index": owner_index,
    }


# ============================================================
# BUILD GLOBAL PRIORITY QUEUE
# ============================================================

def build_processing_queue(spreadsheet):
    proceed_queue = []
    review_queue = []

    available_titles = {
        ws.title
        for ws in spreadsheet.worksheets()
    }

    for sheet_name in CITY_SHEETS:
        if sheet_name not in available_titles:
            print(
                f'Worksheet "{sheet_name}" not found - skipping.'
            )

            continue

        worksheet = spreadsheet.worksheet(
            sheet_name
        )

        info = inspect_worksheet(
            worksheet
        )

        if not info:
            continue

        headers = info["headers"]
        data = info["data"]

        for sheet_row, row in enumerate(
            data,
            start=2
        ):
            # Expand the in-memory row to header length.
            while len(row) < len(headers):
                row.append("")

            decision = normalize_decision(
                row[
                    info["decision_index"]
                ]
            )

            item = {
                "worksheet": worksheet,
                "sheet_name": sheet_name,
                "sheet_row": sheet_row,
                "row": row,
                "url_index": info["url_index"],
                "decision_index": info["decision_index"],
                "phone_index": info["phone_index"],
                "owner_index": info["owner_index"],
            }

            if decision == "PROCEED":
                proceed_queue.append(
                    item
                )

            elif decision == "REVIEW":
                review_queue.append(
                    item
                )

    # Critical:
    # all PROCEED across ALL cities first,
    # then all REVIEW across ALL cities.
    return proceed_queue + review_queue, proceed_queue, review_queue


# ============================================================
# MAIN
# ============================================================

def main():
    spreadsheet = get_spreadsheet()

    processing_queue, proceed_queue, review_queue = (
        build_processing_queue(
            spreadsheet
        )
    )

    print()
    print("=" * 70)
    print(
        "TOTAL PROCEED:",
        len(proceed_queue)
    )
    print(
        "TOTAL REVIEW:",
        len(review_queue)
    )
    print(
        "TOTAL ELIGIBLE:",
        len(processing_queue)
    )
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        context = browser.new_context(
            locale="ar-SA",
            timezone_id="Asia/Riyadh",
            viewport={
                "width": 1366,
                "height": 900,
            },
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 "
                "Safari/537.36"
            ),
        )

        page = context.new_page()

        page.set_default_timeout(
            10000
        )

        total = len(
            processing_queue
        )

        processed = 0
        skipped_complete = 0
        phones_saved = 0
        owners_saved = 0
        brokers_saved = 0

        for current, item in enumerate(
            processing_queue,
            start=1
        ):
            worksheet = item[
                "worksheet"
            ]

            row = item[
                "row"
            ]

            sheet_row = item[
                "sheet_row"
            ]

            url_index = item[
                "url_index"
            ]

            decision_index = item[
                "decision_index"
            ]

            phone_index = item[
                "phone_index"
            ]

            owner_index = item[
                "owner_index"
            ]

            url = str(
                row[url_index]
            ).strip()

            decision = normalize_decision(
                row[decision_index]
            )

            existing_phone = normalize_phone(
                row[phone_index]
                if len(row) > phone_index
                else ""
            )

            existing_owner = (
                str(
                    row[owner_index]
                ).strip()
                if len(row) > owner_index
                else ""
            )

            print()
            print("=" * 70)
            print(
                f"[{current}/{total}] "
                f"{item['sheet_name']} | "
                f"Row {sheet_row} | "
                f"{decision}"
            )

            if (
                existing_phone
                and existing_owner
            ):
                print(
                    "Already completed. Skipping."
                )

                skipped_complete += 1

                continue

            if not url:
                print(
                    "URL empty. Skipping."
                )

                continue

            try:
                result = process_aqar_listing(
                    page,
                    url
                )

                processed += 1

                # --------------------------------------------
                # PHONE
                # --------------------------------------------

                if (
                    result["phone"]
                    and not existing_phone
                ):
                    worksheet.update_cell(
                        sheet_row,
                        phone_index + 1,
                        result["phone"]
                    )

                    phones_saved += 1

                    print(
                        "Saved phone:",
                        result["phone"]
                    )

                # --------------------------------------------
                # OWNER / BROKER
                # --------------------------------------------

                if (
                    result[
                        "owner_or_broker"
                    ]
                    and not existing_owner
                ):
                    worksheet.update_cell(
                        sheet_row,
                        owner_index + 1,
                        result[
                            "owner_or_broker"
                        ]
                    )

                    if result[
                        "owner_or_broker"
                    ] == "مالك":
                        owners_saved += 1

                    elif result[
                        "owner_or_broker"
                    ] == "وسيط":
                        brokers_saved += 1

                    print(
                        "Saved owner_or_broker:",
                        result[
                            "owner_or_broker"
                        ]
                    )

            except Exception as exc:
                print(
                    "Unexpected error:",
                    exc
                )

            delay = random.uniform(
                MIN_DELAY,
                MAX_DELAY
            )

            print(
                f"Waiting {delay:.1f} seconds..."
            )

            time.sleep(
                delay
            )

        browser.close()

    print()
    print("=" * 70)
    print("COMPLETED")
    print(
        "Total PROCEED:",
        len(proceed_queue)
    )
    print(
        "Total REVIEW:",
        len(review_queue)
    )
    print(
        "Processed this run:",
        processed
    )
    print(
        "Already completed/skipped:",
        skipped_complete
    )
    print(
        "New phone numbers saved:",
        phones_saved
    )
    print(
        "New owners saved:",
        owners_saved
    )
    print(
        "New brokers saved:",
        brokers_saved
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
