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

PROMPT_TEMPLATE = """أنت محلل عقاري دقيق جدًا. حلّل وصف إعلان بيع هذا العقار.

بيانات مرجعية عن هذا الإعلان (عشان تتجنب الخلط):
- سعر البيع المعلن: {price} ريال

المطلوب الأول -- هل مؤجّر حاليًا فعليًا:
تأكد إن العقار فيه **مستأجر ساكن الآن بعقد إيجار سكني فعلي**، مو حالات ثانية
تمامًا زي: خطة تقسيط للسعر، دفعة مقدّمة، تمويل بنكي، أو أي مبلغ غير الإيجار.

⚠️ تحذير حرج جدًا -- هذا أهم قاعدة بالتحليل كامل:
- سعر البيع لهذا العقار هو بالضبط **{price} ريال** -- احفظ هالرقم بعناية
- **ممنوع نهائيًا** إنك تضع أي رقم بـannual_rent يساوي أو يقارب سعر البيع
  ({price}) أو أي كسر كبير منه (نص السعر، ثلثه...) -- هذا يعني إنك خلطت
  بين الإيجار والسعر نفسه أو جزء من خطة دفعه، مو إيجار حقيقي إطلاقًا
- لا تعتبر رقم "التقسيط" أو "الدفعات" أو "المقدّم" إيجارًا
- الإيجار السنوي الحقيقي عادة نسبة صغيرة جدًا من سعر البيع (غالبًا 3%-12%
  من {price}، يعني تقريبًا بين {rent_low_estimate} و {rent_high_estimate} ريال
  لهذا العقار بالذات) -- أي رقم بعيد جدًا عن هذا المدى هو غالبًا خطأ
- لو عندك أي شك أو تردد بين رقمين، اختر الأصغر دائمًا، أو ضع null لو مو متأكد
  100% -- الخطأ الآمن هو null، مو رقم غلط
- استخرج الرقم بس لو مذكور صراحة كـ"إيجار سنوي" أو "أجرة سنوية" مرتبط
  بعقد إيجار قائم فعليًا، بصيغة واضحة لا لبس فيها

المطلوب الثاني -- المميزات والتفاصيل:
استخرج أهم المميزات المذكورة (مصعد، موقف سيارة، مسبح، نادي، حديقة، أمن...)،
وحدد بوضوح هل فيه مطبخ مذكور (راكب أو مجهز)، وهل الوحدة مؤثثة بالكامل أو جزئيًا.

نص الوصف:
\"\"\"
{description}
\"\"\"

أرجع JSON فقط (بدون أي نص إضافي أو علامات markdown):

{{
  "is_currently_rented": true أو false,
  "annual_rent": الرقم المذكور بالضبط كإيجار سنوي حقيقي أو null (راجع التحذير أعلاه بعناية),
  "lease_details": "جملة مختصرة عن تفاصيل العقد لو مذكورة، أو نص فارغ",
  "confidence": "عالية" أو "متوسطة" أو "لا يوجد رقم" -- استخدم "لا يوجد رقم" دائمًا لو annual_rent = null، "عالية" فقط لو الرقم صريح جدًا ومنطقي, "متوسطة" لو فيه غموض بسيط,
  "key_features": "قائمة مختصرة بأهم المميزات المذكورة، مفصولة بـ | (مثال: مصعد | موقف سيارة | مسبح)، أو نص فارغ لو ما فيه شي بارز",
  "has_kitchen": true أو false -- هل مذكور مطبخ (راكب/مجهز/عادي) بالوصف,
  "is_furnished": true أو false -- هل الوحدة مؤثثة (كليًا أو جزئيًا) حسب الوصف
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

    # أقصى عائد فعلي منطقي -- أي رقم أعلى من هذا يعتبر خطأ استخراج مؤكد
    # (خلط الإيجار بسعر البيع أو دفعة/تقسيط)، نستبعده بدل ما نثق فيه
    MAX_PLAUSIBLE_YIELD = 20.0

    results = []
    discarded_implausible = 0
    for i, (_, row) in enumerate(candidates.iterrows(), start=1):
        price = row.get("price")
        rent_low_estimate = round(price * 0.03) if price else 0
        rent_high_estimate = round(price * 0.12) if price else 0
        prompt = PROMPT_TEMPLATE.format(
            description=str(row.get("description", ""))[:3500], price=price,
            rent_low_estimate=rent_low_estimate, rent_high_estimate=rent_high_estimate,
        )
        try:
            response_text = call_claude(prompt, api_key)
            result = parse_json_response(response_text)
        except Exception as e:
            print(f"[{i}/{len(candidates)}] فشل تحليل {row.get('listing_id')}: {e}")
            continue

        if not result.get("is_currently_rented"):
            continue

        annual_rent = result.get("annual_rent")

        # فحص مباشر إضافي: نتأكد الرقم المستخرج مو نفس سعر البيع (أو قريب
        # منه جدًا) بغض النظر عن العائد -- طبقة حماية ثانية مستقلة عن حساب
        # النسبة، عشان نلقط أي خلط واضح بسعر البيع أو جزء دائري منه
        is_same_as_price = False
        if annual_rent and price:
            price_ratios = [1.0, 0.5, 0.75, 0.25, 0.9, 0.95]  # نسب شائعة لخلط بالسعر/دفعات
            is_same_as_price = any(abs(annual_rent - price * r) / price < 0.03 for r in price_ratios)

        yield_pct = round(annual_rent / price * 100, 2) if annual_rent and price else None

        # فحص منطقي صارم: لو العائد المحسوب أعلى من المعقول، أو الرقم يطابق
        # سعر البيع (أو نسبة دائرية منه)، الرقم غالبًا خطأ استخراج (خلط
        # بسعر البيع/تقسيط)، نستبعده بدل ما نعرضه كأنه موثوق
        if is_same_as_price or (yield_pct is not None and yield_pct > MAX_PLAUSIBLE_YIELD):
            discarded_implausible += 1
            annual_rent = None
            yield_pct = None
            confidence = "مرفوض -- رقم غير منطقي (يحتمل خلط بسعر البيع)"
        elif annual_rent is None:
            # مؤجّرة فعلًا حسب الوصف، بس بدون رقم إيجار مذكور -- نحتفظ بالصف
            # ونوضح الحالة صراحة، بدل ما نخسر المعلومة كليًا
            confidence = "مؤجّرة -- بدون رقم إيجار مذكور بالوصف"
        else:
            confidence = result.get("confidence")

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
            "lease_confidence": confidence,
            "lease_details": result.get("lease_details"),
            "key_features": result.get("key_features"),
            "has_kitchen": result.get("has_kitchen"),
            "is_furnished": result.get("is_furnished"),
            "description": row.get("description"),
        })

        if i % 10 == 0:
            print(f"[{i}/{len(candidates)}] تمت المعالجة...")
        time.sleep(0.3)

    result_df = pd.DataFrame(results)
    if len(result_df):
        # ترتيب بأولوية: عقارات برقم إيجار موثوق أول (بالعائد تنازليًا)، وبعدها
        # الحالات الناقصة/المرفوضة بآخر الترتيب مع تعليم واضح "تحتاج مراجعة"
        def sort_priority(row):
            if pd.notna(row["yield_pct_actual"]):
                return 0  # رقم موثوق -- أولوية أولى
            return 1  # بدون رقم أو مرفوض -- آخر الترتيب

        result_df["_sort_priority"] = result_df.apply(sort_priority, axis=1)
        result_df["review_status"] = result_df["_sort_priority"].map({
            0: "",
            1: "⚠️ تحتاج مراجعة يدوية -- مؤجّرة لكن بدون رقم إيجار موثوق",
        })
        result_df = result_df.sort_values(
            ["_sort_priority", "yield_pct_actual"], ascending=[True, False]
        ).drop(columns=["_sort_priority"])

    with_rent = result_df["actual_annual_rent"].notna().sum() if len(result_df) else 0
    print(f"\nعقارات مؤجرة فعليًا (مؤكدة): {len(result_df)}")
    print(f"منها برقم إيجار صريح مذكور: {with_rent}")
    print(f"أرقام رُفضت (غير منطقية، يحتمل خلط بسعر البيع): {discarded_implausible}")

    result_df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
