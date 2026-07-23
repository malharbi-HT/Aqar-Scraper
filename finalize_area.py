"""
يدمج نتيجة fix_area_nlp.py بملف نهائي نظيف جاهز للتحليل:
- يستبدل area_sqm بالقيمة المصححة (area_sqm_corrected) لو موجودة
- يحذف أي صف لسا بدون مساحة صحيحة (فشل التصحيح بالكامل)
"""

import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "listings_sale_area_fixed.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, "listings_sale_final.csv")


def main():
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"عدد الصفوف قبل الدمج: {len(df)}")

    # نستخدم المساحة المصححة لو موجودة، وإلا نرجع للأصلية (للصفوف اللي أصلاً ما كانت مشتبهة)
    df["area_sqm"] = df["area_sqm_corrected"].fillna(df["area_sqm"])

    # لكن لو الصف كان مشتبه به (is_project_area_error) والتصحيح فشل، لازم نفرّغه فعليًا
    # (مو نسيب القيمة الخاطئة الأصلية تتسرب)
    still_wrong = df["is_project_area_error"] & df["area_sqm_corrected"].isna()
    df.loc[still_wrong, "area_sqm"] = None

    before_drop = len(df)
    df = df.dropna(subset=["area_sqm", "price"])
    after_drop = len(df)
    print(f"حذفنا {before_drop - after_drop} صف بدون مساحة أو سعر صحيح")

    # ننضف الأعمدة المساعدة اللي ما نحتاجها بعد الآن
    df = df.drop(columns=["area_sqm_corrected", "is_project_area_error"], errors="ignore")

    print(f"عدد الصفوف النهائي: {len(df)}")
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"تم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
