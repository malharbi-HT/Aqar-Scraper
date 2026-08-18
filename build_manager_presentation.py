"""
يبني الجدول النهائي للعرض على المدير:
1. يختار ~20 عقار من yield_from_sakani_indicators.csv (عائد 7-9%، ثقة سكني عالية،
   موزّعين بالتساوي على المناطق -- عيّنة تمثيلية، مو أعلى 20 عشوائي)
2. يشغّل الـ LLM عليهم (استخراج وحدات متعددة + تحقق تعارض بيانات)
3. يضيف التوصية النهائية الموحدة ودرجة الثقة
4. يطلّع جدول نهائي بالأعمدة المطلوبة بالضبط، بدون رقم التواصل
"""

import pandas as pd
import os
import json
import re
import time
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "yield_from_sakani_indicators.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "manager_presentation_report.csv")

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"

YIELD_MIN, YIELD_MAX = 5.5, 9.0
TARGET_SAMPLE_SIZE = 20
STRONG_COMPARISON_MIN_DEALS = 10

PROMPT_TEMPLATE = """أنت محلل عقاري. حلّل وصف الإعلان التالي واستخرج المعلومات بدقة.

بيانات الإعلان المسجّلة عندنا:
- المساحة: {area} م²
- عدد الغرف: {rooms}
- عدد الحمامات: {bathrooms}
- عمر العقار: {age} سنة
- السعر: {price} ريال

نص الوصف:
\"\"\"
{description}
\"\"\"

المطلوب: أرجع JSON فقط (بدون أي نص إضافي أو علامات markdown) بهذا الشكل بالضبط:

{{
  "is_multi_unit": true أو false,
  "units": [
    {{"unit_label": "وصف مختصر للوحدة", "area_sqm": رقم أو null, "rooms": رقم أو null,
      "bathrooms": رقم أو null, "price": رقم أو null}}
  ],
  "data_conflicts": {{
    "area_sqm": القيمة الصحيحة من الوصف أو null,
    "rooms": نفس الشي, "bathrooms": نفس الشي, "age_years": نفس الشي
  }},
  "notes": "ملاحظة مختصرة جدًا أو نص فارغ"
}}

قواعد: لا تخترع وحدات غير مذكورة صراحة. بـ data_conflicts ضع قيمة فقط لو الوصف يذكر رقمًا مختلفًا عن المسجّل."""


def call_claude(prompt, api_key):
    payload = json.dumps({
        "model": MODEL, "max_tokens": 1500,
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


MAX_AGE_YEARS = 10  # نستبعد العقارات الأقدم من هذا من العيّنة كليًا

def pick_diverse_sample(df):
    """يختار عيّنة موزّعة بالتساوي على المناطق، من نطاق العائد المطلوب وثقة عالية"""
    pool = df[
        (df["expected_yield_pct_sakani"] >= YIELD_MIN)
        & (df["expected_yield_pct_sakani"] <= YIELD_MAX)
        & (df["sakani_trusted"] == True)
        & (df["age_years"] <= MAX_AGE_YEARS)
    ].copy()
    print(f"عقارات بنطاق العائد {YIELD_MIN}-{YIELD_MAX}% وثقة عالية: {len(pool)}")

    if len(pool) == 0:
        return pool

    directions = pool["direction"].dropna().unique()
    per_direction = max(1, TARGET_SAMPLE_SIZE // max(len(directions), 1))

    sampled_parts = []
    for d in directions:
        part = pool[pool["direction"] == d].sort_values("expected_yield_pct_sakani", ascending=False).head(per_direction)
        sampled_parts.append(part)

    sample = pd.concat(sampled_parts, ignore_index=True)

    if len(sample) < TARGET_SAMPLE_SIZE:
        remaining = pool[~pool["listing_id"].isin(sample["listing_id"])]
        extra = remaining.sort_values("expected_yield_pct_sakani", ascending=False).head(TARGET_SAMPLE_SIZE - len(sample))
        sample = pd.concat([sample, extra], ignore_index=True)

    sample = sample.head(TARGET_SAMPLE_SIZE)
    print(f"العيّنة النهائية: {len(sample)} عقار، موزّعة على {sample['direction'].nunique()} مناطق")
    print(sample["direction"].value_counts().to_string())
    return sample


def has_conflicts(value):
    text = str(value or "").strip()
    return text not in ("", "{}", "nan", "None")


def compute_confidence(row):
    signals = 0
    if row.get("sakani_trusted") is True:
        signals += 1
    deals_count = row.get("comparable_sale_deals_count")
    if pd.notna(deals_count) and deals_count >= STRONG_COMPARISON_MIN_DEALS:
        signals += 1
    if has_conflicts(row.get("llm_corrections")):
        signals -= 1
    if signals >= 2:
        return "عالية"
    elif signals == 1:
        return "متوسطة"
    return "منخفضة"


def compute_final_verdict(row):
    verdict_price = str(row.get("verdict_price") or "")
    conflicts = has_conflicts(row.get("llm_corrections"))

    if "REVIEW" in verdict_price:
        return "🔴 لا ينصح بها", "سعر البيع أرخص بشكل غير طبيعي مقارنة بصفقات رسمية مشابهة -- تحقق من الصك والمساحة أولًا"
    if not verdict_price or verdict_price == "nan":
        return "⚪ غير مكتمل", "ما توفرت صفقات رسمية كافية للتحقق من عدالة السعر"
    if "مبالغ" in verdict_price:
        return "🟡 تحتاج مراجعة", "سعر البيع أعلى من صفقات رسمية مشابهة -- تفاوض على السعر قبل أي قرار"
    if conflicts:
        return "🟡 تحتاج مراجعة", "السعر عادل، لكن فيه تعارض بين بيانات الإعلان والوصف -- تأكد من التفاصيل الفعلية"
    return "🟢 فرصة قوية", "عائد إيجاري موثّق رسميًا من سكني، وسعر بيع عادل مقارنة بصفقات وزارة العدل، وبدون أي تعارض بالبيانات"


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("تحذير: ما لقيت ANTHROPIC_API_KEY بمتغيرات البيئة")
        return
    if not os.path.exists(INPUT_PATH):
        print(f"تحذير: ما لقيت {INPUT_PATH}")
        return

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"عدد الصفوف الكلي: {len(df)}")

    sample = pick_diverse_sample(df)
    if len(sample) == 0:
        print("ما لقينا أي عقار مطابق للشروط -- جرّب توسيع نطاق العائد")
        return

    output_rows = []
    for i, (_, row) in enumerate(sample.iterrows(), start=1):
        prompt = PROMPT_TEMPLATE.format(
            area=row.get("area_sqm"), rooms=row.get("rooms"),
            bathrooms=row.get("bathrooms"), age=row.get("age_years"),
            price=row.get("price"), description=str(row.get("description", ""))[:4000],
        )
        try:
            response_text = call_claude(prompt, api_key)
            result = parse_json_response(response_text)
        except Exception as e:
            print(f"[{i}/{len(sample)}] فشل تحليل {row['listing_id']}: {e}")
            result = {"is_multi_unit": False, "units": [{}], "data_conflicts": {}, "notes": ""}

        conflicts = result.get("data_conflicts", {}) or {}
        units = result.get("units", []) or [{}]

        for unit in units:
            new_row = row.to_dict()
            new_row["is_multi_unit"] = result.get("is_multi_unit", False)
            new_row["unit_label"] = unit.get("unit_label")
            for field in ["area_sqm", "rooms", "bathrooms", "price"]:
                unit_val = unit.get(field)
                conflict_val = conflicts.get(field)
                if unit_val is not None:
                    new_row[field] = unit_val
                elif conflict_val is not None:
                    new_row[field] = conflict_val
            if conflicts.get("age_years") is not None:
                new_row["age_years"] = conflicts["age_years"]

            found_conflicts = {k: v for k, v in conflicts.items() if v is not None}
            new_row["llm_corrections"] = json.dumps(found_conflicts, ensure_ascii=False)
            new_row["llm_notes"] = result.get("notes", "")

            if found_conflicts:
                conflict_text = "تعارض بيانات اكتشفه التحليل الآلي: " + ", ".join(
                    f"{field}={value} بالوصف (مسجّل عندنا {row.get(field)})"
                    for field, value in found_conflicts.items()
                )
                existing_risks_raw = new_row.get("risks")
                existing_risks = "" if pd.isna(existing_risks_raw) else str(existing_risks_raw).strip()
                new_row["risks"] = (existing_risks + " | " + conflict_text) if existing_risks else conflict_text

            output_rows.append(new_row)

        print(f"[{i}/{len(sample)}] تمت المعالجة -- {row.get('district')}")
        time.sleep(0.3)

    result_df = pd.DataFrame(output_rows)

    verdicts = result_df.apply(compute_final_verdict, axis=1)
    result_df["التوصية_النهائية"] = [v[0] for v in verdicts]
    result_df["سبب_التوصية_النهائية"] = [v[1] for v in verdicts]
    result_df["درجة_الثقة"] = result_df.apply(compute_confidence, axis=1)

    result_df = result_df.rename(columns={
        "expected_yield_pct_sakani": "yield_pct",
        "expected_annual_rent_sakani": "expected_annual_rent",
    })

    # عمود نوع العقار -- كل شي عندنا حاليًا شقق (السحب مقصور على شقق-للبيع بس)
    result_df["نوع_العقار"] = "شقة"

    final_cols = [
        "listing_id", "url", "title", "district", "city", "direction",
        "التوصية_النهائية", "درجة_الثقة", "سبب_التوصية_النهائية",
        "نوع_العقار", "price", "area_sqm", "rooms", "bathrooms", "livings", "age_years", "مؤثثة",
        "yield_pct", "expected_annual_rent", "sakani_deals_count",
        "ratio" if "ratio" in result_df.columns else "price_ratio",
        "verdict_price",
        "verdict_price_reason" if "verdict_price_reason" in result_df.columns else None,
        "strengths", "risks",
        "is_multi_unit", "unit_label", "llm_corrections", "llm_notes",
        "description", "images",
    ]
    final_cols = [c for c in final_cols if c and c in result_df.columns]

    # أعمدة نستبعدها كليًا (مو مفيدة بعرض المدير: بيانات تقنية/إدارية داخلية)
    EXCLUDE_COLS = {
        "images_count", "advertiser_name", "advertiser_company", "advertiser_type",
        "created_at", "published_at", "last_update", "views", "date_scraped",
        "published", "price_text", "price_was_missing", "price_per_sqm",
        "anomaly_score", "is_anomaly", "رقم_التواصل",
    }
    remaining = [c for c in result_df.columns if c not in final_cols and c not in EXCLUDE_COLS]
    result_df = result_df[final_cols + remaining]

    rank = {"🟢 فرصة قوية": 0, "🟡 تحتاج مراجعة": 1, "⚪ غير مكتمل": 2, "🔴 لا ينصح بها": 3}
    result_df["_rank"] = result_df["التوصية_النهائية"].map(rank).fillna(9)
    result_df = result_df.sort_values(["_rank", "yield_pct"], ascending=[True, False]).drop(columns=["_rank"])

    result_df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print(f"\n--- توزيع التوصية النهائية ---")
    print(result_df["التوصية_النهائية"].value_counts().to_string())
    print(f"\n--- توزيع درجة الثقة ---")
    print(result_df["درجة_الثقة"].value_counts().to_string())
    print(f"\nتم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
