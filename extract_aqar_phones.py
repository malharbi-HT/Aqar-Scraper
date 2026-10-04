import os
import re
import time
import random
from pathlib import Path
from urllib.parse import urlparse

import google.auth
import gspread
from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

AQAR_STORAGE_STATE = os.getenv(
    "AQAR_STORAGE_STATE_FILE",
    "aqar_storage_state.json"
)

MIN_DELAY = float(os.getenv("MIN_DELAY", "3"))
MAX_DELAY = float(os.getenv("MAX_DELAY", "5"))
PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "45000"))

# Only actually test 10 PROCEED properties without phone
MAX_PROPERTIES_TO_TEST = int(
    os.getenv("MAX_PROPERTIES_TO_TEST", "10")
)

DEBUG_DIR = Path(
    os.getenv("DEBUG_DIR", "debug")
)

DEBUG_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# CITY SHEETS
# ============================================================

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
# DIGITS
# ============================================================

ARABIC_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789"
)


def normalize_digits(text):
    if text is None:
        return ""

    return str(text).translate(
        ARABIC_DIGITS
    )


# ============================================================
# PHONE
# ============================================================

def normalize_phone(value):
    if not value:
        return ""

    value = normalize_digits(
        value
    )

    digits = re.sub(
        r"\D",
        "",
        value
    )

    if digits.startswith("00966"):
        digits = digits[5:]

    elif digits.startswith("966"):
        digits = digits[3:]

    if (
        len(digits) == 9
        and digits.startswith("5")
    ):
        digits = "0" + digits

    if re.fullmatch(
        r"05\d{8}",
        digits
    ):
        return digits

    return ""


def extract_phone(text):
    if not text:
        return ""

    text = normalize_digits(
        text
    )

    patterns = [
        r"(?:\+?966|00966)[\s\-\.]*5[\s\-\.]*\d{2}[\s\-\.]*\d{3}[\s\-\.]*\d{4}",
        r"05[\s\-\.]*\d{2}[\s\-\.]*\d{3}[\s\-\.]*\d{4}",
        r"\b05\d{8}\b",
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text
        )

        for match in matches:

            phone = normalize_phone(
                match
            )

            if phone:
                return phone

    return ""


# ============================================================
# OWNER / BROKER
# ============================================================

def detect_owner_or_broker(text):
    if not text:
        return ""

    text = normalize_digits(
        text
    ).lower()

    owner_patterns = [
        r"صفة\s*المعلن\s*[:：]?\s*مالك",
        r"نوع\s*المعلن\s*[:：]?\s*مالك",
    ]

    broker_patterns = [
        r"صفة\s*المعلن\s*[:：]?\s*وسيط",
        r"صفة\s*المعلن\s*[:：]?\s*مسوق",
        r"نوع\s*المعلن\s*[:：]?\s*وسيط",
        r"نوع\s*المعلن\s*[:：]?\s*مسوق",
    ]

    for pattern in owner_patterns:
        if re.search(
            pattern,
            text
        ):
            return "مالك"

    for pattern in broker_patterns:
        if re.search(
            pattern,
            text
        ):
            return "وسيط"

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

    return ""


# ============================================================
# LISTING ID
# ============================================================

def get_listing_id(url):
    if not url:
        return "unknown"

    match = re.search(
        r"-(\d+)(?:[/?#]|$)",
        url
    )

    if match:
        return match.group(1)

    path = urlparse(
        url
    ).path

    digits = re.findall(
        r"\d+",
        path
    )

    if digits:
        return digits[-1]

    return "unknown"


# ============================================================
# DEBUG
# ============================================================

def save_debug_files(
    page,
    listing_id,
    stage
):
    prefix = DEBUG_DIR / (
        f"{listing_id}_{stage}"
    )

    try:
        page.screenshot(
            path=str(
                prefix.with_suffix(".png")
            ),
            full_page=True
        )

        print(
            "Saved screenshot:",
            prefix.with_suffix(".png")
        )

    except Exception as exc:
        print(
            "Screenshot error:",
            repr(exc)
        )

    try:
        html = page.content()

        prefix.with_suffix(
            ".html"
        ).write_text(
            html,
            encoding="utf-8"
        )

        print(
            "Saved HTML:",
            prefix.with_suffix(".html")
        )

    except Exception as exc:
        print(
            "HTML save error:",
            repr(exc)
        )

    try:
        text = page.locator(
            "body"
        ).inner_text(
            timeout=10000
        )

        prefix.with_suffix(
            ".txt"
        ).write_text(
            text,
            encoding="utf-8"
        )

        print(
            "Saved visible text:",
            prefix.with_suffix(".txt")
        )

    except Exception as exc:
        print(
            "Text save error:",
            repr(exc)
        )


# ============================================================
# TEL LINKS
# ============================================================

def phone_from_tel_links(page):
    try:
        links = page.locator(
            'a[href^="tel:"]'
        )

        for i in range(
            links.count()
        ):
            href = links.nth(
                i
            ).get_attribute(
                "href"
            )

            if not href:
                continue

            print(
                "Found tel href:",
                href
            )

            phone = extract_phone(
                href
            )

            if phone:
                return phone

    except Exception:
        pass

    return ""


# ============================================================
# CLICK CONTACT
# ============================================================

def click_show_phone(page):
    print(
        "Searching specifically for Aqar contact button..."
    )

    selectors = [
        'button:has-text("اتصال")',
        'a:has-text("اتصال")',
        '[role="button"]:has-text("اتصال")',

        'button:has-text("اتصل")',
        'a:has-text("اتصل")',
        '[role="button"]:has-text("اتصل")',

        'button:has-text("إظهار رقم الاتصال")',
        'a:has-text("إظهار رقم الاتصال")',
        '[role="button"]:has-text("إظهار رقم الاتصال")',

        'button:has-text("عرض رقم الاتصال")',
        'a:has-text("عرض رقم الاتصال")',

        'a[href^="tel:"]',
    ]

    for selector in selectors:
        try:
            locator = page.locator(
                selector
            )

            count = locator.count()

            print(
                f"Selector {selector} found {count} candidate(s)"
            )

            for i in range(count):
                item = locator.nth(i)

                try:
                    if not item.is_visible():
                        continue

                    try:
                        text = item.inner_text().strip()
                    except Exception:
                        text = ""

                    print(
                        "Trying contact element:",
                        text or selector
                    )

                    href = item.get_attribute(
                        "href"
                    )

                    if (
                        href
                        and href.startswith("tel:")
                    ):
                        print(
                            "Contact element already contains tel:",
                            href
                        )

                        return href

                    item.scroll_into_view_if_needed()

                    time.sleep(1)

                    try:
                        item.click(
                            timeout=8000
                        )

                    except Exception as exc:
                        print(
                            "Normal click failed:",
                            repr(exc)
                        )

                        print(
                            "Trying force click..."
                        )

                        item.click(
                            force=True,
                            timeout=8000
                        )

                    print(
                        "Contact button clicked successfully."
                    )

                    return True

                except Exception as exc:
                    print(
                        "Candidate click failed:",
                        repr(exc)
                    )

        except Exception:
            continue

    print(
        "Could not find a visible اتصال button."
    )

    return False


# ============================================================
# DEBUG MODALS
# ============================================================

def print_visible_dialogs(page):
    selectors = [
        '[role="dialog"]',
        '[role="alertdialog"]',
        '[class*="modal"]',
        '[class*="dialog"]',
        '[class*="popup"]',
        '[class*="sheet"]',
    ]

    for selector in selectors:
        try:
            elements = page.locator(
                selector
            )

            for i in range(
                elements.count()
            ):
                element = elements.nth(i)

                if not element.is_visible():
                    continue

                try:
                    text = element.inner_text().strip()
                except Exception:
                    text = ""

                if text:
                    print()
                    print(
                        "VISIBLE DIALOG:"
                    )
                    print(
                        text[:1500]
                    )
                    print()

        except Exception:
            continue


# ============================================================
# LOGIN / OTP CHECK
# ============================================================

def detect_login_or_otp(page):
    try:
        text = page.locator(
            "body"
        ).inner_text(
            timeout=10000
        )

    except Exception:
        return False

    keywords = [
        "تسجيل الدخول",
        "رمز التحقق",
        "رمز التأكيد",
        "أدخل رقم الجوال",
        "ادخل رقم الجوال",
        "رقم الجوال",
        "OTP",
    ]

    found = [
        keyword
        for keyword in keywords
        if keyword.lower() in text.lower()
    ]

    if found:
        print(
            "LOGIN/OTP INDICATORS FOUND:",
            found
        )

        return True

    return False


# ============================================================
# WAIT AFTER CONTACT CLICK
# ============================================================

def wait_for_phone_after_click(
    page,
    listing_id,
    timeout_seconds=15
):
    print(
        "Waiting for phone after اتصال click..."
    )

    print(
        "Current URL after click:",
        page.url
    )

    end_time = (
        time.time()
        + timeout_seconds
    )

    while (
        time.time()
        < end_time
    ):
        phone = phone_from_tel_links(
            page
        )

        if phone:
            print(
                "Phone found from tel link:",
                phone
            )

            return phone

        print_visible_dialogs(
            page
        )

        detect_login_or_otp(
            page
        )

        try:
            text = page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )

            phone = extract_phone(
                text
            )

            if phone:
                print(
                    "Phone appeared after click:",
                    phone
                )

                return phone

        except Exception:
            pass

        time.sleep(1)

    save_debug_files(
        page,
        listing_id,
        "after_click"
    )

    print(
        "No phone appeared after waiting."
    )

    return ""


# ============================================================
# PROCESS LISTING
# ============================================================

def process_aqar_listing(
    page,
    url
):
    result = {
        "phone": "",
        "owner_or_broker": "",
    }

    if not url:
        return result

    if not str(url).startswith(
        "http"
    ):
        return result

    listing_id = get_listing_id(
        url
    )

    print()
    print(
        "Opening:",
        url
    )

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

    except Exception as exc:
        print(
            "Page load warning:",
            repr(exc)
        )

    time.sleep(4)

    print(
        "Loaded URL:",
        page.url
    )

    # --------------------------------------------------------
    # Before click debug
    # --------------------------------------------------------

    detect_login_or_otp(
        page
    )

    # --------------------------------------------------------
    # Visible info
    # --------------------------------------------------------

    try:
        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=15000
        )

    except Exception:
        body_text = ""

    owner_type = detect_owner_or_broker(
        body_text
    )

    if owner_type:
        result[
            "owner_or_broker"
        ] = owner_type

        print(
            "Advertiser:",
            owner_type
        )

    phone = extract_phone(
        body_text
    )

    if phone:
        result[
            "phone"
        ] = phone

        print(
            "Phone found in visible page:",
            phone
        )

        return result

    # --------------------------------------------------------
    # Existing tel
    # --------------------------------------------------------

    phone = phone_from_tel_links(
        page
    )

    if phone:
        result[
            "phone"
        ] = phone

        return result

    # --------------------------------------------------------
    # Contact click
    # --------------------------------------------------------

    print(
        "No visible phone. Trying contact button..."
    )

    clicked = click_show_phone(
        page
    )

    if isinstance(
        clicked,
        str
    ):
        phone = extract_phone(
            clicked
        )

        if phone:
            result[
                "phone"
            ] = phone

            print(
                "Phone found directly from tel link:",
                phone
            )

            return result

    if clicked:
        phone = wait_for_phone_after_click(
            page,
            listing_id,
            timeout_seconds=15
        )

        if phone:
            result[
                "phone"
            ] = phone

            print(
                "PHONE FOUND AFTER CLICK:",
                phone
            )

        try:
            updated_text = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

        except Exception:
            updated_text = ""

        if not result[
            "owner_or_broker"
        ]:
            result[
                "owner_or_broker"
            ] = detect_owner_or_broker(
                updated_text
            )

    else:
        save_debug_files(
            page,
            listing_id,
            "no_contact_button"
        )

        detect_login_or_otp(
            page
        )

    if not result[
        "phone"
    ]:
        print(
            "Phone not found."
        )

    return result


# ============================================================
# GOOGLE SHEET
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


def find_column(
    headers,
    choices
):
    normalized = {}

    for index, header in enumerate(
        headers
    ):
        key = str(
            header
        ).strip().lower()

        if key:
            normalized[
                key
            ] = index

    for choice in choices:
        key = str(
            choice
        ).strip().lower()

        if key in normalized:
            return normalized[
                key
            ]

    return None


def normalize_decision(
    value
):
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
# SHEET INSPECTION
# ============================================================

def inspect_worksheet(
    worksheet
):
    rows = worksheet.get_all_values()

    if not rows:
        return None

    headers = rows[0]
    data = rows[1:]

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

    if (
        url_index is None
        or decision_index is None
    ):
        return None

    if phone_index is None:
        phone_index = len(
            headers
        )

        worksheet.update_cell(
            1,
            phone_index + 1,
            "phone"
        )

        headers.append(
            "phone"
        )

    if owner_index is None:
        owner_index = len(
            headers
        )

        worksheet.update_cell(
            1,
            owner_index + 1,
            "owner_or_broker"
        )

        headers.append(
            "owner_or_broker"
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
# BUILD PROCEED QUEUE
# ============================================================

def build_proceed_queue(
    spreadsheet
):
    queue = []

    titles = {
        ws.title
        for ws in spreadsheet.worksheets()
    }

    for sheet_name in CITY_SHEETS:
        if sheet_name not in titles:
            continue

        worksheet = spreadsheet.worksheet(
            sheet_name
        )

        info = inspect_worksheet(
            worksheet
        )

        if not info:
            continue

        headers = info[
            "headers"
        ]

        for sheet_row, row in enumerate(
            info["data"],
            start=2
        ):
            while len(row) < len(
                headers
            ):
                row.append("")

            decision = normalize_decision(
                row[
                    info[
                        "decision_index"
                    ]
                ]
            )

            if decision != "PROCEED":
                continue

            queue.append(
                {
                    "worksheet": worksheet,
                    "sheet_name": sheet_name,
                    "sheet_row": sheet_row,
                    "row": row,
                    "url_index": info[
                        "url_index"
                    ],
                    "phone_index": info[
                        "phone_index"
                    ],
                    "owner_index": info[
                        "owner_index"
                    ],
                }
            )

    return queue


# ============================================================
# BROWSER
# ============================================================

def create_context(
    browser
):
    options = {
        "locale": "ar-SA",
        "timezone_id": "Asia/Riyadh",
        "viewport": {
            "width": 1366,
            "height": 900,
        },
        "user_agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0.0.0 "
            "Safari/537.36"
        ),
    }

    if os.path.exists(
        AQAR_STORAGE_STATE
    ):
        print(
            "Using saved Aqar session."
        )

        return browser.new_context(
            storage_state=AQAR_STORAGE_STATE,
            **options
        )

    print(
        "WARNING: no Aqar session file."
    )

    return browser.new_context(
        **options
    )


# ============================================================
# MAIN
# ============================================================

def main():
    spreadsheet = get_spreadsheet()

    queue = build_proceed_queue(
        spreadsheet
    )

    print()
    print(
        "TOTAL PROCEED FOUND:",
        len(queue)
    )

    print(
        "TEST LIMIT:",
        MAX_PROPERTIES_TO_TEST
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        context = create_context(
            browser
        )

        page = context.new_page()

        page.set_default_timeout(
            12000
        )

        tested = 0
        phones_saved = 0

        for item in queue:
            if (
                tested
                >= MAX_PROPERTIES_TO_TEST
            ):
                print(
                    "Reached test limit."
                )

                break

            row = item[
                "row"
            ]

            phone_index = item[
                "phone_index"
            ]

            owner_index = item[
                "owner_index"
            ]

            existing_phone = normalize_phone(
                row[
                    phone_index
                ]
                if len(row) > phone_index
                else ""
            )

            # Existing phones do NOT count toward the 10 tests.
            if existing_phone:
                continue

            tested += 1

            print()
            print(
                "=" * 70
            )

            print(
                f"TEST [{tested}/{MAX_PROPERTIES_TO_TEST}] "
                f"{item['sheet_name']} | "
                f"Row {item['sheet_row']}"
            )

            url = str(
                row[
                    item[
                        "url_index"
                    ]
                ]
            ).strip()

            existing_owner = (
                str(
                    row[
                        owner_index
                    ]
                ).strip()
                if len(row) > owner_index
                else ""
            )

            try:
                result = process_aqar_listing(
                    page,
                    url
                )

                if result[
                    "phone"
                ]:
                    item[
                        "worksheet"
                    ].update_cell(
                        item[
                            "sheet_row"
                        ],
                        phone_index + 1,
                        result[
                            "phone"
                        ]
                    )

                    phones_saved += 1

                    print(
                        "SAVED PHONE:",
                        result[
                            "phone"
                        ]
                    )

                if (
                    result[
                        "owner_or_broker"
                    ]
                    and not existing_owner
                ):
                    item[
                        "worksheet"
                    ].update_cell(
                        item[
                            "sheet_row"
                        ],
                        owner_index + 1,
                        result[
                            "owner_or_broker"
                        ]
                    )

            except Exception as exc:
                print(
                    "Unexpected error:",
                    repr(exc)
                )

            delay = random.uniform(
                MIN_DELAY,
                MAX_DELAY
            )

            time.sleep(
                delay
            )

        browser.close()

    print()
    print(
        "=" * 70
    )

    print(
        "TEST COMPLETE"
    )

    print(
        "Listings actually tested:",
        tested
    )

    print(
        "Phones saved:",
        phones_saved
    )

    print(
        "Debug directory:",
        DEBUG_DIR
    )

    print(
        "=" * 70
    )


if __name__ == "__main__":
    main()
