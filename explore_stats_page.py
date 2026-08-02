"""
سكربت استكشافي -- يجيب صفحة "متوسط الأسعار" لحي واحد بعدد غرف محدد،
ويطبع النص المستخرج من RSC عشان نفهم بنية البيانات قبل بناء سكربت الجمع الكامل.
"""

import requests
import re
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.8",
}

# مثال: حي النرجس، شمال الرياض، إيجار، 3 غرف
TEST_URL = "https://sa.aqar.fm/الإحصائيات-العقارية/شقق-للإيجار/الرياض/شمال-الرياض/حي-النرجس?size=3"


def extract_rsc_text(html):
    """نفس دالة استخراج RSC المستخدمة بباقي سكربتات المشروع"""
    pattern = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
    chunks = pattern.findall(html)
    full_text = ""
    for chunk in chunks:
        try:
            full_text += json.loads('"' + chunk + '"')
        except Exception:
            continue
    return full_text


def main():
    print(f"نجيب: {TEST_URL}")
    resp = requests.get(TEST_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    print(f"حجم HTML الخام: {len(resp.text)} حرف")

    rsc_text = extract_rsc_text(resp.text)
    print(f"حجم نص RSC المستخرج: {len(rsc_text)} حرف")

    print("\n--- سياقات حول كلمة 'متوسط' ---")
    for m in re.finditer(r"متوسط", rsc_text):
        start = max(0, m.start() - 100)
        end = min(len(rsc_text), m.end() + 150)
        print(f"...{rsc_text[start:end]}...")
        print()

    with open("rsc_dump.txt", "w", encoding="utf-8") as f:
        f.write(rsc_text)
    print("\nتم حفظ النص الكامل بملف rsc_dump.txt للمراجعة")


if __name__ == "__main__":
    main()
