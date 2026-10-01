import os
import re
import time
import random

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


# =========================================================
# SETTINGS
# =========================================================

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

SHEET_NAME = os.getenv(
    "SHEET_NAME",
    "Riyadh"
)

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ[
    "GOOGLE_SERVICE_ACCOUNT_JSON"
]

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

    if re.fullmatch(
        r"05\d{8}",
        digits
    ):
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

            phone = normalize_phone(
                item
            )

            if phone:
                return phone

    return ""


# =========================================================
# OWNER / BROKER
# =========================================================

def detect_owner_or_broker(text):

    if not text:
        return ""

    text = normalize_digits(
        text
    ).lower()

    # Direct classification from Aqar
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
        "اتصال",
        "اتصل",
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
    ]

    for selector in selectors:

        try:

            buttons = page.locator(
                selector
            )

            for i in range(
                min(buttons.count(), 3)
            ):

                btn = buttons.nth(i)

                if btn.is_visible():

                    btn.scroll_into_view_if_needed()

                    btn.click(
                        timeout=5000
                    )

                    time.sleep(2)

                    return True

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

    print(
        f"Opening {url}"
    )

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
    # FIRST:
    # description + visible information
    # =====================================================

    try:

        body_text = page.locator(
            "body"
        ).inner_text()

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
    # SECOND:
    # existing tel link
    # =====================================================

    phone = phone_from_tel_links(
        page
    )

    if phone:

        result["phone"] = phone

        return result

    # =====================================================
    # THIRD:
    # Show phone button
    # =====================================================

    print(
        "Phone not visible. "
        "Trying Show Contact..."
    )

    clicked = click_show_phone(
        page
    )

    if clicked:

        time.sleep(2)

        phone = phone_from_tel_links(
            page
        )

        if phone:

            result["phone"] = phone

            return result

        try:

            body_text_after = page.locator(
                "body"
            ).inner_text()

        except Exception:

            body_text_after = ""

        phone = extract_phone(
            body_text_after
        )

        if phone:

            result["phone"] = phone

        if not result[
            "owner_or_broker"
        ]:

            result[
                "owner_or_broker"
            ] = detect_owner_or_broker(
                body_text_after
            )

    return result


# =========================================================
# Google Sheet
# =========================================================

def get_google_sheet():

    import json

    service_account_info = json.loads(
        GOOGLE_SERVICE_ACCOUNT_JSON
    )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=scopes
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

        key = name.lower()

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
    # Find existing columns
    # =====================================================

    url_index = find_column(
        headers,
        [
            "url",
            "listing_url",
            "property_url",
            "رابط",
            "رابط العقار",
        ]
    )

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

    # =====================================================
    # Add phone column
    # =====================================================

    phone_index = find_column(
        headers,
        ["phone"]
    )

    if phone_index is None:

        headers.append(
            "phone"
        )

        phone_index = len(
            headers
        ) - 1

        worksheet.update_cell(
            1,
            phone_index + 1,
            "phone"
        )

    # =====================================================
    # Add owner_or_broker
    # =====================================================

    owner_index = find_column(
        headers,
        ["owner_or_broker"]
    )

    if owner_index is None:

        headers.append(
            "owner_or_broker"
        )

        owner_index = len(
            headers
        ) - 1

        worksheet.update_cell(
            1,
            owner_index + 1,
            "owner_or_broker"
        )

    # =====================================================
    # Prepare rows
    # =====================================================

    proceed_rows = []
    review_rows = []

    for sheet_row, row in enumerate(
        data,
        start=2
    ):

        # expand short rows
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

    # PROCEED first
    rows_to_process = (
        proceed_rows
        + review_rows
    )

    print(
        "PROCEED:",
        len(proceed_rows)
    )

    print(
        "REVIEW:",
        len(review_rows)
    )

    print(
        "TOTAL:",
        len(rows_to_process)
    )

    # =====================================================
    # Browser
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
            }
        )

        page = context.new_page()

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
            )

            existing_owner = row[
                owner_index
            ].strip()

            print()
            print(
                f"[{current}/"
                f"{len(rows_to_process)}]"
            )

            print(
                f"Sheet row: {sheet_row}"
            )

            print(
                f"Decision: {decision}"
            )

            # Already complete
            if (
                existing_phone
                and existing_owner
            ):

                print(
                    "Already completed."
                )

                continue

            result = process_aqar_listing(
                page,
                url
            )

            # ================================================
            # Write PHONE
            # ================================================

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

            # ================================================
            # Write OWNER / BROKER
            # ================================================

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
                    "Saved:",
                    result[
                        "owner_or_broker"
                    ]
                )

            delay = random.uniform(
                MIN_DELAY,
                MAX_DELAY
            )

            time.sleep(
                delay
            )

        browser.close()

    print(
        "Completed."
    )


if __name__ == "__main__":
    main()
