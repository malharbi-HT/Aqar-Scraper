from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    context = browser.new_context()
    page = context.new_page()

    page.goto("https://sa.aqar.fm/")

    print("سجلي دخولك في عقار وأدخلي OTP.")

    input("بعد نجاح تسجيل الدخول، ارجعي هنا واضغطي Enter...")

    context.storage_state(path="aqar_storage_state.json")

    print("تم حفظ الجلسة.")

    browser.close()
