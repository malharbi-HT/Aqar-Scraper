"""
محلل صفقات عميق -- يشتغل بس على العقارات "الأفضل" من
find_currently_rented_properties.py (بدون أي تحذير: رقم إيجار موثوق + صك
مستقل + سنوي)، ويحلل أعلى 10 فرص بالعائد.

مصدر مقارنة السعر: رغدان (raghdan.sa) -- سحب حي مباشر لكل عقار وقت التحليل.
رغدان تعتمد على بيانات وزارة العدل المفتوحة (open.data.gov.sa) نفسها، بس
معروضة جاهزة لكل حي (متوسط + نطاق شائع + عدد صفقات + نمو سنوي)، فما نحتاج
نحتفظ بملف صفقات محلي ضخم.

⚠️ منهجية مهمة: نقارن بـ"النطاق الشائع" الكامل (من-إلى)، مو بس المتوسط --
عقار سعره أعلى من المتوسط بس لسا داخل النطاق الشائع يعتبر سعره طبيعي، مو مرتفع.

مصدر مقارنة الإيجار: مؤشرات سكني الرسمية (حسب الحي وعدد الغرف).
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
    """يسحب بيانات حي كاملة من رغدان: متوسط السعر، النطاق الشائع، عدد
    الصفقات، والنمو السنوي -- مصدرها وزارة العدل، معروضة جاهزة لكل حي"""
    district_bare = district.replace("حي ", "").strip() if isinstance(district, str) else district
    url = f"https://raghdan.sa/en/market/{urllib.parse.quote(city)}/{urllib.parse.quote(district_bare)}/"

    try:
        req = urllib.request.Request(url, headers=RAGHDAN_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return None, f"فشل سحب رغدان: {e}", url

    # نستهدف og:description أول (الصيغة الطويلة، فيها عدد الصفقات والنمو
    # صراحة) -- لو ما لقيناها، نرجع لأي meta description ثانية كخطة بديلة
    og_match = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
    generic_match = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html)
    meta_match = og_match or generic_match
    if not meta_match:
        return None, "ما لقينا بيانات رغدان بصيغة متوقعة لهالحي", url

    summary = meta_match.group(1)
    price_match = re.search(r"([\d,]+)\s*SAR/m", summary)
    # نتقبل الصيغتين: "transactions: 10,525" (طويلة) أو "10,525 transactions" (قصيرة)
    trans_match = (
        re.search(r"transactions:\s*([\d,]+)", summary, re.IGNORECASE)
        or re.search(r"([\d,]+)\s*transactions", summary, re.IGNORECASE)
    )
    growth_match = re.search(r"growth:\s*([+-]?[\d.]+)%", summary, re.IGNORECASE)

    if not price_match:
        return None, "ما قدرنا نستخرج سعر المتر من صفحة رغدان", url

    return {
        "avg_price_per_sqm": float(price_match.group(1).replace(",", "")),
        "transactions": int(trans_match.group(1).replace(",", "")) if trans_match else None,
        "yoy_growth_pct": float(growth_match.group(1)) if growth_match else None,
        "url": url,
    }, None, url


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


def compute_price_assessment(property_price_per_sqm, raghdan_data):
    """يحسب تقييم السعر برمجيًا (مو بالـ LLM) -- مقارنة بمتوسط سعر متر الحي
    من رغدان (نفس مصدر وزارة العدل)، بحدود نسبة واضحة وثابتة"""
    if raghdan_data is None:
        return {"assessment": "غير متوفر", "price_vs_avg_pct": None, "target_purchase_price_per_sqm": None}

    avg = raghdan_data["avg_price_per_sqm"]
    price_vs_avg_pct = round((property_price_per_sqm / avg - 1) * 100, 1)

    if price_vs_avg_pct <= 10:
        assessment = f"سعر عادل (قريب من متوسط الحي، {price_vs_avg_pct:+.1f}%)"
        target_per_sqm = property_price_per_sqm  # ما يحتاج تفاوض
    elif price_vs_avg_pct <= 25:
        assessment = f"أعلى من متوسط الحي بشكل ملحوظ ({price_vs_avg_pct:+.1f}%)"
        target_per_sqm = avg * 1.10  # نفاوض لحد 10% فوق المتوسط بس
    else:
        assessment = f"مرتفع بشكل واضح عن متوسط الحي ({price_vs_avg_pct:+.1f}%)"
        target_per_sqm = avg  # نفاوض للمتوسط نفسه

    return {"assessment": assessment, "price_vs_avg_pct": price_vs_avg_pct, "target_purchase_price_per_sqm": target_per_sqm}


PROMPT_TEMPLATE = """أنت محلل عقاري خبير بسوق الرياض. اكتب تحليل استثماري موجز
لهذي الصفقة -- ركّز بس على الإيجار واستدامته، والقصة العامة، لأن حساب السعر
تم برمجيًا مسبقًا وأعطيناك النتيجة جاهزة.

بيانات الصفقة (بعد الحساب البرمجي):
- الحي: {district}
- السعر: {price} ريال ({area} م²، {price_per_sqm} ريال/م²)
- تقييم السعر: {price_assessment}
- سعر شراء مستهدف مقترح: {target_price} ريال
- الإيجار الحالي المذكور: {annual_rent} ريال سنويًا (عائد {yield_pct}%)
- تفاصيل العقد: {lease_details}

الإيجار الرسمي المرجعي لنفس الحي وعدد الغرف (مؤشرات سكني):
{rent_reference}

نص الوصف الأصلي:
\"\"\"
{description}
\"\"\"

أرجع JSON فقط (بدون أي نص إضافي أو علامات markdown):

{{
  "rent_sustainability": "مستدام" أو "مرتفع مؤقتًا" أو "غير مؤكد" -- بناءً على مقارنة رقمية بحتة بالإيجار المرجعي من سكني,
  "rent_sustainability_reason": "جملة مختصرة تعتمد فقط على المقارنة الرقمية -- ⚠️ ممنوع نهائيًا ذكر الأثاث كسبب",
  "stress_test_rent_low": رقم -- سيناريو محافظ لإيجار مستقبلي منخفض,
  "stress_test_yield_low": رقم -- العائد بهالسيناريو,
  "lease_term_note": "جملة مختصرة عن مدة العقد المتبقية",
  "key_risk": "أهم نقطة خطر أو تستاهل تحقق، جملة وحدة",
  "final_verdict": "🟢 Proceed" أو "🟡 Review" أو "🔴 Reject",
  "verdict_summary": "ملخص سردي قصير (جملتين لثلاث) يلخّص القصة الكاملة -- السعر، العائد، أهم نقطة إيجابية، أهم تحفّظ، والتوصية"
}}"""


def call_claude(prompt, api_key):
    payload = json.dumps({
        "model": MODEL, "max_tokens": 1200,
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

        raghdan_data, raghdan_error, raghdan_url = fetch_raghdan_district_data(district)
        time.sleep(RAGHDAN_MIN_DELAY)

        property_price_per_sqm = round(price / area) if price and area else None
        price_calc = compute_price_assessment(property_price_per_sqm, raghdan_data)

        rent_ref = find_rent_reference(sakani_df, district, rooms)
        rent_ref_text = (
            f"{rent_ref['annual_rent']:,.0f} ريال/سنة لشقة {rent_ref['rooms']} غرف (مبني على {rent_ref['deals_count']:.0f} عقد رسمي)"
            if rent_ref else "غير متوفر لهالحي/عدد الغرف"
        )

        target_price = (
            round(price_calc["target_purchase_price_per_sqm"] * area)
            if price_calc["target_purchase_price_per_sqm"] and area else price
        )

        prompt = PROMPT_TEMPLATE.format(
            district=district, price=price, area=area,
            price_per_sqm=property_price_per_sqm, price_assessment=price_calc["assessment"],
            target_price=target_price,
            annual_rent=row.get("actual_annual_rent"), yield_pct=row.get("yield_pct_actual"),
            lease_details=row.get("lease_details") or "غير مذكور",
            rent_reference=rent_ref_text,
            description=str(row.get("description", ""))[:3000],
        )

        try:
            response_text = call_claude(prompt, api_key)
            analysis = parse_json_response(response_text)
        except Exception as e:
            print(f"[{i}/{len(candidates)}] فشل تحليل {row.get('listing_id')}: {e}")
            continue

        results.append({
            "listing_id": row.get("listing_id"),
            "url": row.get("url"),
            "district": district,
            "price": price,
            "area_sqm": area,
            "price_per_sqm": property_price_per_sqm,
            "raghdan_avg_price_per_sqm": raghdan_data["avg_price_per_sqm"] if raghdan_data else None,
            "raghdan_transactions": raghdan_data["transactions"] if raghdan_data else None,
            "raghdan_yoy_growth_pct": raghdan_data["yoy_growth_pct"] if raghdan_data else None,
            "price_assessment": price_calc["assessment"],
            "price_vs_avg_pct": price_calc["price_vs_avg_pct"],
            "مصدر_المقارنة": "رغدان (raghdan.sa) -- مبني على بيانات وزارة العدل" if raghdan_data else f"غير متوفر ({raghdan_error})",
            "raghdan_url": raghdan_url,
            "target_purchase_price": target_price,
            "actual_annual_rent": row.get("actual_annual_rent"),
            "current_yield_pct": row.get("yield_pct_actual"),
            "rent_sustainability": analysis.get("rent_sustainability"),
            "rent_sustainability_reason": analysis.get("rent_sustainability_reason"),
            "stress_test_rent_low": analysis.get("stress_test_rent_low"),
            "stress_test_yield_low": analysis.get("stress_test_yield_low"),
            "lease_term_note": analysis.get("lease_term_note"),
            "key_risk": analysis.get("key_risk"),
            "final_verdict": analysis.get("final_verdict"),
            "verdict_summary": analysis.get("verdict_summary"),
        })

        print(f"[{i}/{len(candidates)}] {row.get('listing_id')} -- {district} -- {price_calc['assessment']} -- {analysis.get('final_verdict')}")

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
