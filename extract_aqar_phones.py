import os
import re
import time
import random

import google.auth
import gspread
from playwright.sync_api import sync_playwright


# =========================================================
# SETTINGS
# =========================================================

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

SHEET_NAME = os.getenv(
    "SHEET_NAME",
    "Riyadh"
)

MIN_DELAY = 3
MAX_DELAY = 7


# =========================================================
# PHONE
# =========================================================

ARABIC_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789"
)


def normalize_digits(text):
    return str(text).translate(ARABIC_DIGITS)


def normalize_phone(value):
    if not value:
        return ""

    value = normalize_digits(value)

    digits = re.sub(
        r"\D",
        "",
        value
    )

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
        r"(?:\+?966|00966)[\s\-\.]*5[\s\-\.]*\d{2}[\s\-\.]*\d{3}[\s\-\.]*\d{4}",
        r"05[\s\-\.]*\d{2}[\s\-\.]*\d{3}[\s\-\.]*\d{4}",
        r"\b05\d{8}\b",
    ]

    for pattern in patterns:
        matches = re.findall(
            pattern,
            text
        )

        for item in matches:
            phone = normalize_phone(item)

            if phone:
                return phone

    return ""


# =========================================================
# OWNER / BROKER
# =========================================================

def detect_owner_or_broker(text):

    if not text:
        return ""

    text = normalize_digits(text).lower()

    # Explicit classification from Aqar
    if re.search(
        r"صفة\s*المعلن\s*[:：]?\s*مالك",
        text
    ):
        return "مالك"

    if re.search(
        r"صفة\s*المعلن\s*[:：]?\s*(وسيط|مسوق)",
        text
    ):
        return "وسيط"

    broker_words = [
        "وسيط عقاري",
        "وسيط",
        "مسوق عقاري",
        "رخصة فال",
        "رقم عقد الوساطة",
        "عقد الوساطة",
        "مكتب عقاري",
        "شركة عقارية",
        "مؤسسة عقارية",
    ]

    for word in broker_words:
        if word in text:
            return "وسيط"

    owner_words = [
        "من المالك مباشرة",
        "مباشر من المالك",
        "المالك مباشرة",
        "مالك العقار",
    ]

    for word in owner_words:
        if word in text:
            return "مالك"

    return ""


# =========================================================
# CONTACT BUTTON
# =========================================================

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

            phone = extract_phone(
                href
            )

            if phone:
                return phone

    except Exception:
        pass

    return ""


def click_show_phone(page):

    labels = [
        "إظهار رقم الاتصال",
        "إظهار الرقم",
        "عرض رقم الاتصال",
        "عرض الرقم",
        "رقم الاتصال",
        "اتصال",
        "اتصل",
        "تواصل",
    ]

    for label in labels:

        try:
            loc = page.get_by_text(
                label,
                exact=True
            )

            count = loc.count()

            for i in range(
                min(count, 3)
            ):
                item = loc.nth(i)

                try:
                    if item.is_visible():
                        item.scroll_into_view_if_needed()

                        time.sleep(0.5)

                        item.click(
                            timeout=5000
                        )

                        time.sleep(2)

                        return True

                except Exception:
                    continue

        except Exception:
            continue

    selectors = [
        'button:has-text("اتصال")',
        'button:has-text("إظهار")',
        '[role="button"]:has-text("اتصال")',
        '[role="button"]:has-text("إظهار")',
        'a[href^="tel:"]',
    ]

    for selector in selectors:

        try:
            items = page.locator(
                selector
            )

            for i in range(
                min(items.count(), 3)
            ):
                item = items.nth(i)

                try:
                    if item.is_visible():

                        href = item.get_attribute(
                            "href"
                        )

                        if href and href.startswith("tel:"):
                            return href

                        item.scroll_into_view_if_needed()

                        item.click(
                            timeout=5000
                        )

                        time.sleep(2)

                        return True

                except Exception:
                    continue

        except Exception:
            continue

    return False


# =========================================================
# Aqar listing
# =========================================================

def process_aqar_listing(page, url):

    result = {
        "phone": "",
        "owner_or_broker": ""
    }

    if not url.startswith("http"):
        return result

    print(f"Opening {url}")

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=45000
        )

    except Exception as exc:
        print(
            "Page load error:",
            exc
        )

    time.sleep(3)

    # =====================================================
    # 1. DESCRIPTION + VISIBLE INFO
    # =====================================================

    try:
        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=10000
        )

    except Exception:
        body_text = ""

    result[
        "owner_or_broker"
    ] = detect_owner_or_broker(
        body_text
    )

    phone = extract_phone(
        body_text
    )

    if phone:
        print(
            "Phone found before click:",
            phone
        )

        result["phone"] = phone

        return result

    # =====================================================
    # 2. TEL LINKS
    # =====================================================

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

    # =====================================================
    # 3. CLICK SHOW CONTACT
    # =====================================================

    print(
        "Phone not visible. Trying contact button..."
    )

    clicked = click_show_phone(
        page
    )

    if isinstance(clicked, str):

        phone = extract_phone(
            clicked
        )

        if phone:
            result["phone"] = phone

            return result

    if clicked:

        time.sleep(2)

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

        try:
            body_text_after = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

        except Exception:
            body_text_after = ""

        phone = extract_phone(
            body_text_after
        )

        if phone:
            print(
                "Phone revealed after click:",
                phone
            )

            result["phone"] = phone

        if not result[
            "owner_or_broker"
        ]:

            result[
                "owner_or_broker"
            ] = detect_owner_or_broker(
                body_text_after
            )

    if not result["phone"]:
        print("Phone not found")

    return result


# =========================================================
# GOOGLE SHEET USING WORKLOAD IDENTITY
# =========================================================

def get_google_sheet():

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

    return spreadsheet.worksheet(
        SHEET_NAME
    )


def find_column(headers, choices):

    normalized = {
        h.strip().lower(): i
        for i, h in enumerate(headers)
    }

    for name in choices:

        key = name.strip().lower()

        if key in normalized:
            return normalized[key]

    return None


# =========================================================
# MAIN
# =========================================================

def main():

    worksheet = get_google_sheet()

    all_rows = worksheet.get_all_values()

    if not all_rows:
        raise RuntimeError(
            "Google Sheet is empty."
        )

    headers = all_rows[0]

    data = all_rows[1:]

    print(
        "Total rows:",
        len(data)
    )

    # =====================================================
    # Find URL column
    # =====================================================

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

    # =====================================================
    # Find Decision column
    # =====================================================

    decision_index = find_column(
        headers,
        [
            "decision",
            "initial_verdict",
            "verdict",
            "القرار",
        ]
    )

    if url_index is None:
        raise RuntimeError(
            "URL column not found."
        )

    if decision_index is None:
        raise RuntimeError(
            "Decision column not found."
        )

    print(
        "URL column:",
        headers[url_index]
    )

    print(
        "Decision column:",
        headers[decision_index]
    )

    # =====================================================
    # Add phone
    # =====================================================

    phone_index = find_column(
        headers,
        [
            "phone"
        ]
    )

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

        print(
            "Added phone column."
        )

    # =====================================================
    # Add owner_or_broker
    # =====================================================

    owner_index = find_column(
        headers,
        [
            "owner_or_broker"
        ]
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

        print(
            "Added owner_or_broker column."
        )

    # =====================================================
    # PRIORITY
    # PROCEED -> REVIEW
    # IGNORE REJECT
    # =====================================================

    proceed_rows = []
    review_rows = []

    for sheet_row, row in enumerate(
        data,
        start=2
    ):

        while len(row) < len(headers):
            row.append("")

        decision = row[
            decision_index
        ].strip().upper()

        if decision in [
            "PROCEED",
            "بروسيد"
        ]:

            proceed_rows.append(
                (sheet_row, row)
            )

        elif decision in [
            "REVIEW",
            "ريفيو"
        ]:

            review_rows.append(
                (sheet_row, row)
            )

    rows_to_process = (
        proceed_rows
        + review_rows
    )

    print()
    print(
        "PROCEED:",
        len(proceed_rows)
    )

    print(
        "REVIEW:",
        len(review_rows)
    )

    print(
        "TOTAL TO PROCESS:",
        len(rows_to_process)
    )

    # =====================================================
    # BROWSER
    # =====================================================

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
            rows_to_process
        )

        for current, (
            sheet_row,
            row
        ) in enumerate(
            rows_to_process,
            start=1
        ):

            url = row[
                url_index
            ].strip()

            decision = row[
                decision_index
            ].strip()

            existing_phone = normalize_phone(
                row[phone_index]
                if len(row) > phone_index
                else ""
            )

            existing_owner = (
                row[owner_index].strip()
                if len(row) > owner_index
                else ""
            )

            print()
            print(
                f"[{current}/{total}]"
            )

            print(
                "Sheet row:",
                sheet_row
            )

            print(
                "Decision:",
                decision
            )

            # Already complete
            if (
                existing_phone
                and existing_owner
            ):

                print(
                    "Already completed. Skipping."
                )

                continue

            try:
                result = process_aqar_listing(
                    page,
                    url
                )

                # ==========================================
                # WRITE PHONE
                # ==========================================

                if (
                    result["phone"]
                    and not existing_phone
                ):

                    worksheet.update_cell(
                        sheet_row,
                        phone_index + 1,
                        result["phone"]
                    )

                    print(
                        "Saved phone:",
                        result["phone"]
                    )

                # ==========================================
                # WRITE OWNER / BROKER
                # ==========================================

                if (
                    result["owner_or_broker"]
                    and not existing_owner
                ):

                    worksheet.update_cell(
                        sheet_row,
                        owner_index + 1,
                        result[
                            "owner_or_broker"
                        ]
                    )

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
                f"Waiting {delay:.1f}s"
            )

            time.sleep(
                delay
            )

        browser.close()

    print()
    print(
        "Completed."
    )


if __name__ == "__main__":
    main()
