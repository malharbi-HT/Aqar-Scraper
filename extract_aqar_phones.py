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

# Optional.
# If empty or not found, first worksheet will be used automatically.
SHEET_NAME = os.getenv("SHEET_NAME", "").strip()

MIN_DELAY = float(os.getenv("MIN_DELAY", "3"))
MAX_DELAY = float(os.getenv("MAX_DELAY", "7"))

PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "45000"))


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
# PHONE
# ============================================================

def normalize_phone(value):
    """
    Convert Saudi mobile numbers to:
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
    """
    Search Saudi mobile number in supplied text.
    """

    if not text:
        return ""

    text = normalize_digits(text)

    patterns = [
        # +966551234567 / +966 55 123 4567
        r"(?:\+?966|00966)[\s\-\.]*5[\s\-\.]*\d{2}[\s\-\.]*\d{3}[\s\-\.]*\d{4}",

        # 055 123 4567 / 055-123-4567
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

    # --------------------------------------------------------
    # Explicit Aqar classifications first
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Strong broker indicators
    # --------------------------------------------------------

    broker_keywords = [
        "وسيط عقاري",
        "مسوق عقاري",
        "وسيط ومسوق عقاري",
        "رخصة فال",
        "ترخيص فال",
        "رقم عقد الوساطة",
        "عقد الوساطة",
        "مكتب عقاري",
        "شركة عقارية",
        "مؤسسة عقارية",
    ]

    for keyword in broker_keywords:

        if keyword in text:
            return "وسيط"

    # --------------------------------------------------------
    # Strong owner indicators
    # --------------------------------------------------------

    owner_keywords = [
        "من المالك مباشرة",
        "مباشر من المالك",
        "المالك مباشرة",
        "مالك العقار",
        "أنا المالك",
        "انا المالك",
    ]

    for keyword in owner_keywords:

        if keyword in text:
            return "مالك"

    return ""


# ============================================================
# PHONE FROM TEL LINKS
# ============================================================

def phone_from_tel_links(page):

    try:

        links = page.locator('a[href^="tel:"]')

        count = links.count()

        for i in range(count):

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
# CLICK CONTACT BUTTON
# ============================================================

def click_show_phone(page):

    labels = [
        "إظهار رقم الاتصال",
        "إظهار الرقم",
        "عرض رقم الاتصال",
        "عرض الرقم",
        "رقم الاتصال",
        "اتصال",
        "اتصل",
    ]

    # --------------------------------------------------------
    # Try exact visible text
    # --------------------------------------------------------

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

                    item.scroll_into_view_if_needed()

                    time.sleep(0.5)

                    href = item.get_attribute("href")

                    if href and href.startswith("tel:"):
                        return href

                    item.click(
                        timeout=5000
                    )

                    time.sleep(2)

                    return True

                except Exception:
                    continue

        except Exception:
            continue

    # --------------------------------------------------------
    # Try common selectors
    # --------------------------------------------------------

    selectors = [
        'button:has-text("إظهار رقم الاتصال")',
        'button:has-text("إظهار الرقم")',
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


# ============================================================
# PROCESS ONE Aqar LISTING
# ============================================================

def process_aqar_listing(page, url):

    result = {
        "phone": "",
        "owner_or_broker": "",
    }

    if not url:
        return result

    if not str(url).startswith("http"):
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
            "Page loading warning:",
            exc
        )

    # Allow JS content to render
    time.sleep(3)

    # ========================================================
    # STEP 1:
    # Search visible page content first
    # Description + additional information + advertiser info
    # ========================================================

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
            "Phone found in visible information:",
            phone
        )

        result["phone"] = phone

        return result

    # ========================================================
    # STEP 2:
    # Look for hidden/available tel links
    # ========================================================

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

    # ========================================================
    # STEP 3:
    # No phone found.
    # Click contact button.
    # ========================================================

    print(
        "Phone not visible. Trying contact button..."
    )

    clicked = click_show_phone(
        page
    )

    # Sometimes the function itself returns tel:...
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

        # ----------------------------------------------------
        # Try tel link after click
        # ----------------------------------------------------

        phone = phone_from_tel_links(
            page
        )

        if phone:

            print(
                "Phone found after contact click:",
                phone
            )

            result["phone"] = phone

            return result

        # ----------------------------------------------------
        # Read page again after modal/reveal
        # ----------------------------------------------------

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
        print(
            "Phone not found."
        )

    if not result["owner_or_broker"]:
        print(
            "Owner/Broker not determined."
        )

    return result


# ============================================================
# GOOGLE SHEETS
# WORKLOAD IDENTITY FEDERATION
# ============================================================

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

    print(
        "Google Sheet opened:",
        spreadsheet.title
    )

    # --------------------------------------------------------
    # If SHEET_NAME is supplied, try it
    # --------------------------------------------------------

    if SHEET_NAME:

        try:

            worksheet = spreadsheet.worksheet(
                SHEET_NAME
            )

            print(
                "Using requested worksheet:",
                worksheet.title
            )

            return worksheet

        except gspread.exceptions.WorksheetNotFound:

            print(
                f'Worksheet "{SHEET_NAME}" was not found.'
            )

            print(
                "Falling back to first worksheet."
            )

    # --------------------------------------------------------
    # Otherwise use first tab
    # --------------------------------------------------------

    worksheets = spreadsheet.worksheets()

    if not worksheets:

        raise RuntimeError(
            "No worksheets found inside Google Sheet."
        )

    worksheet = worksheets[0]

    print(
        "Automatically using worksheet:",
        worksheet.title
    )

    return worksheet


# ============================================================
# COLUMN HELPERS
# ============================================================

def find_column(headers, choices):

    normalized = {
        str(header).strip().lower(): index
        for index, header in enumerate(headers)
    }

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
# MAIN
# ============================================================

def main():

    worksheet = get_google_sheet()

    all_rows = worksheet.get_all_values()

    if not all_rows:

        raise RuntimeError(
            "Google Sheet is empty."
        )

    headers = all_rows[0]

    data = all_rows[1:]

    print()
    print(
        "Total rows:",
        len(data)
    )

    # ========================================================
    # FIND URL COLUMN
    # ========================================================

    url_index = find_column(
        headers,
        [
            "url",
            "URL",
            "listing_url",
            "property_url",
            "link",
            "رابط",
            "رابط العقار",
        ]
    )

    if url_index is None:

        raise RuntimeError(
            "URL column was not found."
        )

    print(
        "URL column:",
        headers[url_index]
    )

    # ========================================================
    # FIND DECISION COLUMN
    # ========================================================

    decision_index = find_column(
        headers,
        [
            "decision",
            "Decision",
            "initial_verdict",
            "verdict",
            "status",
            "القرار",
        ]
    )

    if decision_index is None:

        raise RuntimeError(
            "Decision column was not found."
        )

    print(
        "Decision column:",
        headers[decision_index]
    )

    # ========================================================
    # ADD PHONE COLUMN
    # ========================================================

    phone_index = find_column(
        headers,
        [
            "phone"
        ]
    )

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
            "Added column: phone"
        )

    # ========================================================
    # ADD OWNER/BROKER COLUMN
    # ========================================================

    owner_index = find_column(
        headers,
        [
            "owner_or_broker"
        ]
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
            "Added column: owner_or_broker"
        )

    # ========================================================
    # PREPARE PRIORITY
    #
    # 1. PROCEED
    # 2. REVIEW
    # REJECT ignored
    # ========================================================

    proceed_rows = []
    review_rows = []

    for sheet_row, row in enumerate(
        data,
        start=2
    ):

        while len(row) < len(headers):
            row.append("")

        decision = normalize_decision(
            row[decision_index]
        )

        if decision == "PROCEED":

            proceed_rows.append(
                (sheet_row, row)
            )

        elif decision == "REVIEW":

            review_rows.append(
                (sheet_row, row)
            )

    rows_to_process = (
        proceed_rows
        + review_rows
    )

    print()
    print(
        "PROCEED rows:",
        len(proceed_rows)
    )

    print(
        "REVIEW rows:",
        len(review_rows)
    )

    print(
        "TOTAL eligible rows:",
        len(rows_to_process)
    )

    # ========================================================
    # BROWSER
    # ========================================================

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

        processed = 0
        phones_found = 0
        owners_found = 0
        brokers_found = 0

        for current, (
            sheet_row,
            row
        ) in enumerate(
            rows_to_process,
            start=1
        ):

            print()
            print(
                "=" * 70
            )

            print(
                f"[{current}/{total}] "
                f"Google Sheet row {sheet_row}"
            )

            url = str(
                row[url_index]
            ).strip()

            decision = normalize_decision(
                row[decision_index]
            )

            existing_phone = ""

            if len(row) > phone_index:

                existing_phone = normalize_phone(
                    row[phone_index]
                )

            existing_owner = ""

            if len(row) > owner_index:

                existing_owner = str(
                    row[owner_index]
                ).strip()

            print(
                "Decision:",
                decision
            )

            # ------------------------------------------------
            # Skip completed rows
            # ------------------------------------------------

            if (
                existing_phone
                and existing_owner
            ):

                print(
                    "Already completed. Skipping."
                )

                continue

            if not url:

                print(
                    "URL is empty. Skipping."
                )

                continue

            # ------------------------------------------------
            # Process Aqar
            # ------------------------------------------------

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

                    phones_found += 1

                    print(
                        "Saved phone:",
                        result["phone"]
                    )

                # --------------------------------------------
                # OWNER / BROKER
                # --------------------------------------------

                if (
                    result["owner_or_broker"]
                    and not existing_owner
                ):

                    worksheet.update_cell(
                        sheet_row,
                        owner_index + 1,
                        result["owner_or_broker"]
                    )

                    if result["owner_or_broker"] == "مالك":
                        owners_found += 1

                    elif result["owner_or_broker"] == "وسيط":
                        brokers_found += 1

                    print(
                        "Saved owner_or_broker:",
                        result["owner_or_broker"]
                    )

            except Exception as exc:

                print(
                    "Unexpected error:",
                    exc
                )

            # ------------------------------------------------
            # Delay
            # ------------------------------------------------

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

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print(
        "=" * 70
    )

    print(
        "COMPLETED"
    )

    print(
        "Eligible PROCEED:",
        len(proceed_rows)
    )

    print(
        "Eligible REVIEW:",
        len(review_rows)
    )

    print(
        "Processed this run:",
        processed
    )

    print(
        "New phone numbers saved:",
        phones_found
    )

    print(
        "New owners identified:",
        owners_found
    )

    print(
        "New brokers identified:",
        brokers_found
    )

    print(
        "=" * 70
    )


if __name__ == "__main__":
    main()
