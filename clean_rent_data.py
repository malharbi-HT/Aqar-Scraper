"""
سكربت واحد يجمع كل منطق تنظيف الإيجار (استبعاد شهري، وأي منطق إضافي لاحقًا)
كدوال منفصلة تشتغل بالتتابع على نفس الملف الرئيسي.

المبدأ: ما نحذف أي صف أبدًا -- نعلّمه بعمود exclusion_reason. أول سبب يوصل
لصف يفوز (ما نعيد الكتابة فوقه). بالنهاية نصدّر نسخة "نظيفة" منفصلة (بس المقبول)
جاهزة للنموذج، ونطبع تقرير توفيق يوضح الحسابات.
"""

import re
import sys
import pandas as pd
from rent_pipeline_utils import load_master, save_master, tag_exclusion, print_reconciliation, DATA_DIR
import os

sys.path.insert(0, os.path.dirname(__file__))
from fix_area_nlp_rent import looks_like_project_area, pick_best_area
from fix_price_nlp_rent import (
    is_marketing_request, is_actually_sale, looks_like_wrong_price,
    extract_price_from_description,
)

CLEAN_EXPORT_PATH = os.path.join(DATA_DIR, "listings_rent_clean.csv")

# ============================================================
# 1) استبعاد الإيجار الشهري
# ============================================================

MONTHLY_PATTERN = re.compile(r"(?:الإيجار|الايجار|إيجار|ايجار)\s*(?:ال)?شهري")
NEGATION_WORDS = ("لا نقبل", "ما نقبل", "لا يقبل", "غير مسموح", "لا يوجد", "بدون")
ANNUAL_PATTERN = re.compile(r"(?:ايجار|إيجار)\s*سنوي\s*[:\s]*([\d,]{4,})")


def _is_monthly(row):
    text = f"{row.get('title', '')} {row.get('description', '')}"
    matches = list(MONTHLY_PATTERN.finditer(text))
    if not matches:
        return False
    for m in matches:
        window_before = text[max(0, m.start() - 20):m.start()]
        if any(neg in window_before for neg in NEGATION_WORDS):
            continue
        annual_match = ANNUAL_PATTERN.search(text)
        if annual_match:
            annual_value = float(annual_match.group(1).replace(",", ""))
            price = row.get("price")
            try:
                if pd.notna(price) and abs(annual_value - float(price)) / max(annual_value, 1) < 0.1:
                    continue
            except Exception:
                pass
        return True
    return False


def exclude_monthly(df):
    untagged = df[df["exclusion_reason"].isna()]
    mask_series = untagged.apply(_is_monthly, axis=1)
    full_mask = pd.Series(False, index=df.index)
    full_mask.loc[untagged.index] = mask_series
    df, count = tag_exclusion(df, full_mask, "monthly_rent")
    print(f"[استبعاد الشهري] علّمنا {count} صف")
    return df


# ============================================================
# 2) تصحيح المساحة من نص الوصف (نفس منطق fix_area_nlp.py المستخدم بالبيع)
# ============================================================

def fix_area(df):
    """يصحح المساحة لو مشتبه بها (فوق 500م²)، ويعلّم المستحيل تصحيحه"""
    active = df[df["exclusion_reason"].isna()].copy()

    active["is_project_area_error"] = active.apply(looks_like_project_area, axis=1)
    suspicious = active[active["is_project_area_error"]]
    print(f"[تصحيح المساحة] عدد الصفوف المشتبه بمساحتها: {len(suspicious)}")

    fixed_count = 0
    uncorrectable_idx = []
    for idx in suspicious.index:
        corrected = pick_best_area(df.loc[idx])
        if corrected:
            df.at[idx, "area_sqm"] = corrected
            fixed_count += 1
        else:
            uncorrectable_idx.append(idx)

    print(f"[تصحيح المساحة] صُحح تلقائيًا: {fixed_count}")
    print(f"[تصحيح المساحة] يستحيل تصحيحه (سنعلّمه للاستبعاد): {len(uncorrectable_idx)}")

    mask = pd.Series(False, index=df.index)
    mask.loc[uncorrectable_idx] = True
    df, count = tag_exclusion(df, mask, "area_uncorrectable")
    return df


# ============================================================
# (هنا نضيف دوال جديدة لاحقًا: exclude_marketing_posts، إلخ)
# كل دالة جديدة نضيفها هنا، ونستدعيها بترتيبها بدالة main()
# ============================================================

def exclude_marketing_posts(df):
    """يستبعد طلبات التسويق الوهمية (مو إعلانات عقار حقيقية)"""
    untagged = df["exclusion_reason"].isna()
    is_marketing = df.loc[untagged, "description"].apply(is_marketing_request)
    mask = pd.Series(False, index=df.index)
    mask.loc[untagged[untagged].index] = is_marketing
    df, count = tag_exclusion(df, mask, "marketing_post")
    print(f"[طلبات تسويق] علّمنا {count} صف")
    return df


def exclude_actually_sale(df):
    """يستبعد إعلانات 'إيجار' اللي هي فعليًا بيع متصنّف غلط"""
    untagged = df["exclusion_reason"].isna()
    is_sale = df.loc[untagged, "description"].apply(is_actually_sale)
    mask = pd.Series(False, index=df.index)
    mask.loc[untagged[untagged].index] = is_sale
    df, count = tag_exclusion(df, mask, "actually_sale")
    print(f"[بيع متصنّف كإيجار] علّمنا {count} صف")
    return df


def fix_price(df):
    """يقارن السعر بالعمود مع السعر المستخرج من الوصف، ويصحح أو يعلّم المستحيل"""
    active_idx = df[df["exclusion_reason"].isna()].index
    print(f"[تصحيح السعر] نستخرج السعر من {len(active_idx)} وصف (يستغرق شوي)...")

    extracted = df.loc[active_idx, "description"].apply(extract_price_from_description)
    is_wrong = df.loc[active_idx].apply(
        lambda row: looks_like_wrong_price(row, extracted.get(row.name)), axis=1
    )

    # حد أدنى مطلق: أي إيجار سنوي تحت هذا الرقم مستحيل يكون حقيقي بالرياض
    ABSOLUTE_MIN_RENT = 5_000
    absurdly_low = df.loc[active_idx, "price"] < ABSOLUTE_MIN_RENT
    is_wrong = is_wrong | absurdly_low

    wrong_idx = active_idx[is_wrong]
    print(f"[تصحيح السعر] صفوف فيها احتمال خطأ: {len(wrong_idx)}")

    fixed_count = 0
    uncorrectable_idx = []
    for idx in wrong_idx:
        new_price = extracted.get(idx)
        if new_price:
            df.at[idx, "price"] = new_price
            fixed_count += 1
        else:
            uncorrectable_idx.append(idx)

    print(f"[تصحيح السعر] صُحح تلقائيًا: {fixed_count}")
    print(f"[تصحيح السعر] يستحيل تصحيحه: {len(uncorrectable_idx)}")

    mask = pd.Series(False, index=df.index)
    mask.loc[uncorrectable_idx] = True
    df, _ = tag_exclusion(df, mask, "price_uncorrectable")
    return df


def main():
    df = load_master()
    print(f"عدد الصفوف الكلي: {len(df)}")

    df = exclude_monthly(df)
    df = fix_area(df)
    df = exclude_marketing_posts(df)
    df = exclude_actually_sale(df)
    df = fix_price(df)

    save_master(df)
    print_reconciliation(df, "بعد كل خطوات الاستبعاد")

    # نصدّر نسخة نظيفة (بس المقبول) -- هذا اللي يدخل بالنموذج لاحقًا
    clean = df[df["exclusion_reason"].isna()].drop(columns=["exclusion_reason"])
    clean.to_csv(CLEAN_EXPORT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nتم تصدير النسخة النظيفة: {CLEAN_EXPORT_PATH} ({len(clean)} صف)")


if __name__ == "__main__":
    main()
