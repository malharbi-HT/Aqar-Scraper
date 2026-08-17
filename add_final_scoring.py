"""
يضيف عمودين نهائيين للتقرير (آخر خطوة بالسلسلة، بعد الـ LLM):

1. التوصية_النهائية -- تجمع كل الإشارات المتاحة (العائد + عدالة السعر + تعارضات
   البيانات) بحكم واحد واضح، بدل ما المستخدم يربطها بنفسه.

2. درجة_الثقة -- توضح قوة الحكم بناءً على كم مصدر تحقق متوفر لهذا العقار:
   عالية = عائد موثّق رسميًا + مقارنة صفقات كافية + بدون تعارضات
   متوسطة = مصدر تحقق واحد بس متوفر
   منخفضة = تقدير نموذج فقط، بدون أي تحقق رسمي
"""

import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "llm_verified_units.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "final_report_scored.csv")

# حد أدنى من الصفقات المشابهة عشان نعتبر مقارنة السعر "قوية"
STRONG_COMPARISON_MIN_DEALS = 10


def has_conflicts(value):
    """هل الـ LLM اكتشف تعارض بيانات فعلي بهذا الصف"""
    text = str(value or "").strip()
    return text not in ("", "{}", "nan", "None")


def compute_confidence(row):
    """درجة الثقة: كم مصدر تحقق مستقل متوفر لهذا العقار"""
    signals = 0

    # إشارة 1: الإيجار من مصدر رسمي موثّق (حي من الـ11)
    if row.get("ضمن_الـ11_حي_التجريبية") in (True, "True", "TRUE"):
        signals += 1

    # إشارة 2: مقارنة سعر بصفقات رسمية كافية
    deals_count = row.get("comparable_deals_count")
    if pd.notna(deals_count) and deals_count >= STRONG_COMPARISON_MIN_DEALS:
        signals += 1

    # خصم: تعارض بيانات مكتشف يقلل الثقة
    if has_conflicts(row.get("llm_corrections")):
        signals -= 1

    if signals >= 2:
        return "عالية"
    elif signals == 1:
        return "متوسطة"
    else:
        return "منخفضة"


def compute_final_verdict(row):
    """التوصية الموحدة: تجمع العائد + عدالة السعر + التعارضات بحكم واحد"""
    verdict_yield = str(row.get("verdict_yield") or "")
    verdict_price = str(row.get("verdict_price") or "")
    conflicts = has_conflicts(row.get("llm_corrections"))

    # أخطر إشارة: سعر مريب جدًا مقارنة بصفقات حقيقية
    if "REVIEW" in verdict_price:
        return "🔴 لا ينصح بها", "سعر البيع أرخص بشكل غير طبيعي مقارنة بصفقات رسمية مشابهة -- تحقق من الصك والمساحة أولًا"

    # ما عندنا مقارنة سعر أصلاً -- حكم ناقص
    if not verdict_price or verdict_price == "nan":
        return "⚪ غير مكتمل", "ما توفرت صفقات رسمية كافية للتحقق من عدالة السعر -- الحكم مبني على تقدير العائد فقط"

    # سعر مبالغ فيه -- فرصة ضعيفة حتى لو العائد يبدو جيد
    if "مبالغ" in verdict_price:
        return "🟡 تحتاج مراجعة", "سعر البيع أعلى من صفقات رسمية مشابهة -- تفاوض على السعر قبل أي قرار"

    # سعر عادل + تعارض بيانات -- يحتاج تدقيق
    if conflicts:
        return "🟡 تحتاج مراجعة", "السعر عادل، لكن فيه تعارض بين بيانات الإعلان والوصف -- تأكد من التفاصيل الفعلية"

    # سعر عادل + عائد قوي + بدون تعارضات = الحالة المثالية
    if "🟢" in verdict_yield:
        return "🟢 فرصة قوية", "عائد إيجاري قوي، وسعر بيع عادل مقارنة بصفقات رسمية، وبدون أي تعارض بالبيانات"

    return "🟡 تحتاج مراجعة", "سعر عادل وعائد مقبول -- راجع التفاصيل قبل القرار"


def main():
    if not os.path.exists(INPUT_PATH):
        print(f"تحذير: ما لقيت {INPUT_PATH} -- شغّل llm_extract_units.py أول")
        return

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"عدد الصفوف: {len(df)}")

    verdicts = df.apply(compute_final_verdict, axis=1)
    df["التوصية_النهائية"] = [v[0] for v in verdicts]
    df["سبب_التوصية_النهائية"] = [v[1] for v in verdicts]
    df["درجة_الثقة"] = df.apply(compute_confidence, axis=1)

    # نرتّب الأعمدة: التوصية والثقة أول (الأهم للقراءة)، والوصف الطويل آخر شي
    priority_cols = ["listing_id", "التوصية_النهائية", "درجة_الثقة", "سبب_التوصية_النهائية",
                     "url", "district", "price", "area_sqm", "rooms", "bathrooms",
                     "yield_low_pct", "price_per_sqm", "ratio"]
    priority_cols = [c for c in priority_cols if c in df.columns]
    other_cols = [c for c in df.columns if c not in priority_cols and c != "description"]
    final_order = priority_cols + other_cols + (["description"] if "description" in df.columns else [])
    df = df[final_order]

    # نرتّب الصفوف: الفرص القوية أول، وداخل كل فئة نرتّب بالعائد الأعلى
    verdict_rank = {"🟢 فرصة قوية": 0, "🟡 تحتاج مراجعة": 1, "⚪ غير مكتمل": 2, "🔴 لا ينصح بها": 3}
    df["_rank"] = df["التوصية_النهائية"].map(verdict_rank).fillna(9)
    sort_cols = ["_rank"] + (["yield_low_pct"] if "yield_low_pct" in df.columns else [])
    df = df.sort_values(sort_cols, ascending=[True] + [False] * (len(sort_cols) - 1)).drop(columns=["_rank"])

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print("\n--- توزيع التوصية النهائية ---")
    print(df["التوصية_النهائية"].value_counts().to_string())
    print("\n--- توزيع درجة الثقة ---")
    print(df["درجة_الثقة"].value_counts().to_string())
    print("\n--- التقاطع (التوصية × الثقة) ---")
    print(pd.crosstab(df["التوصية_النهائية"], df["درجة_الثقة"]).to_string())
    print(f"\nتم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
