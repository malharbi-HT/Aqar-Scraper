"""
محلل صفقات عميق -- يشتغل بس على العقارات "الأفضل" من
find_currently_rented_properties.py (بدون أي تحذير)، ويحلل أعلى 10 فرص بالعائد.

مصدر مقارنة السعر: متوسط سعر متر الحي من رغدان (raghdan.sa) -- سحب حي مباشر
وقت التحليل، مبني على بيانات وزارة العدل المفتوحة.

مصدر مقارنة الإيجار: مؤشرات سكني الرسمية (حسب الحي وعدد الغرف).

الجدول النهائي: بيانات أساسية + عمود التوصية (Proceed/Review/Reject) + عمود
"تفاصيل" أخير فيه نفس أسلوب التحليل السردي الكامل (سعر المتر، العائد،
استدامة الإيجار، اختبار ضغط، سعر شراء مقترح).
"""

import pandas as pd
import os
import re
import json
import time
import urllib.request
import urllib.parse

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
RENTED_PATH = os.path.join(DATA_DIR, "currently_rented_properties.csv")
SAKANI_PATH = os.path.join(DATA_DIR, "sakani_rent_indicators.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "deep_analysis_rented_properties.csv")

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"

RAGHDAN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en,ar;q=0.8",
}
RAGHDAN_MIN_DELAY = 2.0


def fetch_raghdan_district_data(district, city="الرياض"):
    """يسحب متوسط سعر متر الحي من رغدان -- مبني على بيانات وزارة العدل المفتوحة"""
    district_bare = district.replace("حي ", "").strip() if isinstance(district, str) else district
    url = f"https://raghdan.sa/en/market/{urllib.parse.quote(city)}/{urllib.parse.quote(district_bare)}/"

    try:
        req = urllib.request.Request(url, headers=RAGHDAN_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None, url

    og_match = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
    generic_match = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html)
    meta_match = og_match or generic_match
    if not meta_match:
        return None, url

    summary = meta_match.group(1)
    price_match = re.search(r"([\d,]+)\s*SAR/m", summary)
    trans_match = (
        re.search(r"transactions:\s*([\d,]+)", summary, re.IGNORECASE)
        or re.search(r"([\d,]+)\s*transactions", summary, re.IGNORECASE)
    )
    if not price_match:
        return None, url

    return {
        "avg_price_per_sqm": float(price_match.group(1).replace(",", "")),
        "transactions": int(trans_match.group(1).replace(",", "")) if trans_match else None,
    }, url


def find_rent_reference(sakani_df, district, rooms):
    """يجيب الإيجار السنوي الرسمي المتوقع من مؤشرات سكني، حسب الحي وعدد الغرف"""
    if sakani_df is None:
        return None
    district_bare = district.replace("حي ", "").strip() if isinstance(district, str) else district
    match = sakani_df[sakani_df["الحي"] == district_bare]
    if len(match) == 0:
        return None

    col_map = {2: "متوسط السعر غرفتين", 3: "متوسط السعر ثلاث غرف", 4: "متوسط السعر اربع غرف"}
    count_map = {2: "عدد الصفقات غرفتين", 3: "عدد الصفقات ثلاث غرف", 4: "عدد الصفقات اربع غرف "}
    rooms_int = int(rooms) if pd.notna(rooms) else None
    if rooms_int not in col_map:
        return None

    row = match.iloc[0]
    rent = row[col_map[rooms_int]]
    count = row[count_map[rooms_int]]
    if pd.isna(rent) or pd.isna(count):
        return None
    return {"annual_rent": rent * 1000, "deals_count": count, "rooms": rooms_int}


PROMPT_TEMPLATE = """أنت محلل عقاري خبير بسوق الرياض. حلّل صفقة الشراء التالية
بعمق، بنفس أسلوب تحليل استثماري احترافي مفصّل: سعر المتر ومقارنته بالسوق،
العائد الحالي، استدامة الإيجار، اختبار ضغط بسيناريو محافظ، وسعر شراء مقترح
للتفاوض.

بيانات الصفقة:
- الحي: {district}
- السعر: {price} ريال ({area} م²، {price_per_sqm} ريال/م²)
- الإيجار الحالي المذكور: {annual_rent} ريال سنويًا (عائد {yield_pct}%)
- تفاصيل العقد: {lease_details}

متوسط سعر متر الحي (رغدان، مبني على وزارة العدل): {raghdan_avg}
{raghdan_trans}

الإيجار الرسمي المرجعي لنفس الحي وعدد الغرف (مؤشرات سكني):
{rent_reference}

نص الوصف الأصلي:
\"\"\"
{description}
\"\"\"

⚠️ تحذير حرج بخصوص الإيجار: السعر المذكور أعلاه ({annual_rent} ريال) هو
**الإيجار السنوي الكامل بالفعل**، حتى لو مذكور بالوصف "على دفعتين" أو "كل 6
أشهر" -- لا تضاعفه أبدًا بأي حساب أو تفسير.

أرجع JSON فقط (بدون أي نص إضافي أو علامات markdown):

{{
  "target_purchase_price": رقم -- سعر شراء مستهدف للتفاوض، مبني على مقارنة سعر المتر بمتوسط الحي وعائد مستهدف معقول,
  "final_verdict": "🟢 Proceed" أو "🟡 Review" أو "🔴 Reject",
  "تفاصيل": "ملخص سردي كامل ومفصّل (فقرة أو فقرتين) يغطي: سعر المتر ومقارنته بمتوسط الحي، العائد الحالي بالحساب، استدامة الإيجار مقارنة بمرجع سكني، اختبار ضغط بسيناريو محافظ (رقم بديل للإيجار والعائد الناتج)، أي ملاحظة مهمة، وسعر الشراء المقترح مع تبرير الرقم"
}}"""


def call_claude(prompt, api_key):
    payload = json.dumps({
        "model": MODEL, "max_tokens": 1500,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=payload, method="POST",
        headers={"content-type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(block.get("text", "") for block in data.get("content", []))


def parse_json_response(text):
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    return json.loads(cleaned)


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("تحذير: ما لقيت ANTHROPIC_API_KEY بمتغيرات البيئة")
        return
    if not os.path.exists(RENTED_PATH):
        print(f"تحذير: ما لقيت {RENTED_PATH} -- شغّل find_currently_rented_properties.py أول")
        return

    rented = pd.read_csv(RENTED_PATH, encoding="utf-8-sig")
    print(f"إجمالي العقارات المؤجّرة المكتشفة: {len(rented)}")

    if "review_status" in rented.columns:
        candidates = rented[rented["review_status"].fillna("") == ""].copy()
    else:
        candidates = rented[rented["yield_pct_actual"].notna()].copy()

    if "yield_pct_actual" in candidates.columns:
        candidates = candidates.sort_values("yield_pct_actual", ascending=False)
    candidates = candidates.head(1)
    print(f"العشرة الأفضل المختارة للتحليل العميق: {len(candidates)}")

    if len(candidates) == 0:
        print("ما فيه أي عقار مؤهّل حاليًا للتحليل العميق")
        return

    sakani_df = pd.read_csv(SAKANI_PATH, encoding="utf-8-sig") if os.path.exists(SAKANI_PATH) else None

    results = []
    for i, (_, row) in enumerate(candidates.iterrows(), start=1):
        district = row.get("district")
        area = row.get("area_sqm")
        price = row.get("price")
        rooms = row.get("rooms")
        listing_id = row.get("listing_id")

        raghdan_data, raghdan_url = fetch_raghdan_district_data(district)
        time.sleep(RAGHDAN_MIN_DELAY)
        raghdan_avg_text = f"{raghdan_data['avg_price_per_sqm']:,.0f} ريال/م²" if raghdan_data else "غير متوفر"
        raghdan_trans_text = (
            f"(مبني على {raghdan_data['transactions']:,} صفقة مسجّلة)"
            if raghdan_data and raghdan_data.get("transactions") else ""
        )

        property_price_per_sqm = round(price / area) if price and area else None

        rent_ref = find_rent_reference(sakani_df, district, rooms)
        rent_ref_text = (
            f"{rent_ref['annual_rent']:,.0f} ريال/سنة لشقة {rent_ref['rooms']} غرف (مبني على {rent_ref['deals_count']:.0f} عقد رسمي)"
            if rent_ref else "غير متوفر لهالحي/عدد الغرف"
        )

        prompt = PROMPT_TEMPLATE.format(
            district=district, price=price, area=area, price_per_sqm=property_price_per_sqm,
            annual_rent=row.get("actual_annual_rent"), yield_pct=row.get("yield_pct_actual"),
            lease_details=row.get("lease_details") or "غير مذكور",
            raghdan_avg=raghdan_avg_text, raghdan_trans=raghdan_trans_text,
            rent_reference=rent_ref_text,
            description=str(row.get("description", ""))[:3000],
        )

        try:
            response_text = call_claude(prompt, api_key)
            analysis = parse_json_response(response_text)
        except Exception as e:
            print(f"[{i}/{len(candidates)}] فشل تحليل {listing_id}: {e}")
            continue

        results.append({
            "listing_id": listing_id,
            "url": row.get("url"),
            "district": district,
            "price": price,
            "area_sqm": area,
            "price_per_sqm": property_price_per_sqm,
            "actual_annual_rent": row.get("actual_annual_rent"),
            "current_yield_pct": row.get("yield_pct_actual"),
            "target_purchase_price": analysis.get("target_purchase_price"),
            "final_verdict": analysis.get("final_verdict"),
            "تفاصيل": analysis.get("تفاصيل"),
        })

        print(f"[{i}/{len(candidates)}] {listing_id} -- {district} -- {analysis.get('final_verdict')}")

    result_df = pd.DataFrame(results)
    if len(result_df):
        rank = {"🟢 Proceed": 0, "🟡 Review": 1, "🔴 Reject": 2}
        result_df["_rank"] = result_df["final_verdict"].map(rank).fillna(9)
        result_df = result_df.sort_values(["_rank", "current_yield_pct"], ascending=[True, False]).drop(columns=["_rank"])

    result_df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nتم تحليل {len(result_df)} عقار بعمق")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
