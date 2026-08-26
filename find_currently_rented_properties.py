"""
منهجية جديدة: يكتشف العقارات المذكور صراحة إنها مؤجّرة حاليًا، ويستخرج قيمة
الإيجار الفعلي المذكورة بنص الإعلان -- ويحسب العائد مباشرة من هذا الرقم
الحقيقي، بدون أي مقارنة بمؤشرات سكني أو صفقات وزارة العدل.

المنطق: لو المعلن يذكر "مؤجرة بعقد سنوي X ريال"، هذا رقم حقيقي موقّع لنفس
الوحدة بالذات -- أدق من أي تقدير إحصائي عام.

خطوتين:
1. فلترة أولية رخيصة (Regex) -- تلقط بس الإعلانات اللي تذكر كلمات التأجير
2. Claude يحلل كل مرشّح بدقة -- يتأكد فعلاً مؤجرة، ويستخرج الإيجار السنوي الدقيق
"""

import pandas as pd
import os
import re
import json
import time
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "listings_sale_normal.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "currently_rented_properties.csv")

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"

# فلترة أولية رخيصة -- كلمات تدل على وجود مستأجر حاليًا
RENTED_HINTS = re.compile(
    r"مؤجرة|مؤجر\b|يوجد مستأجر|مستأجر حاليًا|مستأجر حاليا|عقد إيجار ساري|"
    r"عقد إيجار سنوي|مؤجّرة|مؤجّر\b"
)

PROMPT_TEMPLATE = """أنت محلل عقاري. حلّل وصف إعلان بيع هذا العقار، وحدد بدقة:
هل هو مؤجّر حاليًا فعليًا (فيه مستأجر ساكن الآن بعقد فعلي)، ولو كذا كم قيمة
الإيجار السنوي المذكورة بالضبط.

⚠️ مهم: لا تخمّن رقم -- استخرج بس لو مذكور صراحة بالنص. لو الإعلان يذكر
"مؤجرة" بدون رقم، ضع is_currently_rented=true و annual_rent=null.

نص الوصف:
\"\"\"
{description}
\"\"\"

أرجع JSON فقط (بدون أي نص إضافي أو علامات markdown):

{{
  "is_currently_rented": true أو false,
  "annual_rent": الرقم المذكور بالضبط أو null,
  "lease_details": "جملة مختصرة عن تفاصيل العقد لو مذكورة (نوع العقد، تاريخ الانتهاء...)، أو نص فارغ",
  "confidence": "عالية" أو "متوسطة" -- عالية لو الرقم صريح جدًا بالنص، متوسطة لو فيه غموض بسيط
}}"""


def call_claude(prompt, api_key):
    payload = json.dumps({
        "model": MODEL, "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=payload, method="POST",
        headers={"content-type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
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
    if not os.path.exists(INPUT_PATH):
        print(f"تحذير: ما لقيت {INPUT_PATH}")
        return

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"إجمالي العقارات: {len(df)}")

    candidates = df[df["description"].fillna("").astype(str).str.contains(RENTED_HINTS, na=False)].copy()
    print(f"مرشّحين (يذكرون تأجير بالوصف): {len(candidates)}")

    if len(candidates) == 0:
        print("ما لقينا أي مرشّح -- توقف هنا")
        return

    results = []
    for i, (_, row) in enumerate(candidates.iterrows(), start=1):
        prompt = PROMPT_TEMPLATE.format(description=str(row.get("description", ""))[:3500])
        try:
            response_text = call_claude(prompt, api_key)
            result = parse_json_response(response_text)
        except Exception as e:
            print(f"[{i}/{len(candidates)}] فشل تحليل {row.get('listing_id')}: {e}")
            continue

        if not result.get("is_currently_rented"):
            continue

        annual_rent = result.get("annual_rent")
        price = row.get("price")
        yield_pct = round(annual_rent / price * 100, 2) if annual_rent and price else None

        results.append({
            "listing_id": row.get("listing_id"),
            "url": row.get("url"),
            "title": row.get("title"),
            "district": row.get("district"),
            "direction": row.get("direction"),
            "price": price,
            "area_sqm": row.get("area_sqm"),
            "rooms": row.get("rooms"),
            "bathrooms": row.get("bathrooms"),
            "age_years": row.get("age_years"),
            "actual_annual_rent": annual_rent,
            "yield_pct_actual": yield_pct,
            "lease_confidence": result.get("confidence"),
            "lease_details": result.get("lease_details"),
            "description": row.get("description"),
        })

        if i % 10 == 0:
            print(f"[{i}/{len(candidates)}] تمت المعالجة...")
        time.sleep(0.3)

    result_df = pd.DataFrame(results)
    if len(result_df):
        result_df = result_df.sort_values("yield_pct_actual", ascending=False)

    with_rent = result_df["actual_annual_rent"].notna().sum() if len(result_df) else 0
    print(f"\nعقارات مؤجرة فعليًا (مؤكدة): {len(result_df)}")
    print(f"منها برقم إيجار صريح مذكور: {with_rent}")

    result_df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
