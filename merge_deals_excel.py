"""
يفك ضغط ملفي "الكل ٢٠٢٥.xlsx.zip" و"الكل ٢٠٢٦.xlsx.zip" (صفقات وزارة العدل
الخام)، ويدمجهم بملف CSV واحد جاهز لاستخدامه بـ compare_sale_to_deals.py.

نستخدم هذا الأسلوب (رفع ملفات مضغوطة صغيرة + دمج تلقائي بالسكربت) بدل رفع
ملف CSV ضخم مباشرة، لأن رفع GitHub عبر المتصفح محدود الحجم (~25 ميجا).
"""

import pandas as pd
import zipfile
import glob
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "sale_deals_riyadh_2025_2026.csv")

# نبحث عن أي ملف .zip بمجلد data فيه كلمة "الكل" -- يشمل أي اسم قريب من
# "الكل ٢٠٢٥.xlsx.zip" بغض النظر عن اختلافات بسيطة بالتسمية
ZIP_PATTERN = os.path.join(DATA_DIR, "*الكل*.zip")

EXTRACT_DIR = os.path.join(DATA_DIR, "_extracted_deals")


def extract_and_read(zip_path):
    """يفك ضغط ملف zip، ويقرأ أول ملف xlsx بداخله"""
    with zipfile.ZipFile(zip_path, "r") as z:
        xlsx_names = [n for n in z.namelist() if n.lower().endswith(".xlsx")]
        if not xlsx_names:
            print(f"  تحذير: ما لقيت أي ملف xlsx داخل {zip_path}")
            return None
        z.extractall(EXTRACT_DIR)
        xlsx_path = os.path.join(EXTRACT_DIR, xlsx_names[0])
        print(f"  استخرجنا: {xlsx_names[0]}")
        return pd.read_excel(xlsx_path)


def main():
    zip_files = glob.glob(ZIP_PATTERN)
    print(f"لقينا {len(zip_files)} ملف مضغوط بمجلد data/: {zip_files}")

    if not zip_files:
        print("تحذير: ما لقيت أي ملف .zip فيه كلمة 'الكل' بمجلد data/")
        return

    os.makedirs(EXTRACT_DIR, exist_ok=True)

    all_dfs = []
    for zip_path in zip_files:
        print(f"\nنعالج: {zip_path}")
        df = extract_and_read(zip_path)
        if df is not None:
            # نحدد السنة من اسم الملف نفسه (٢٠٢٥ أو ٢٠٢٦)
            year = "2025" if "٢٠٢٥" in zip_path or "2025" in zip_path else "2026"
            df["السنة_المصدر"] = year
            print(f"  عدد الصفوف: {len(df)}")
            all_dfs.append(df)

    if not all_dfs:
        print("تحذير: ما قدرنا نقرأ أي ملف بنجاح")
        return

    merged = pd.concat(all_dfs, ignore_index=True)
    print(f"\nإجمالي الصفوف بعد الدمج: {len(merged)}")

    if "رقم الصفقة" in merged.columns:
        before = len(merged)
        merged = merged.drop_duplicates(subset="رقم الصفقة", keep="first")
        print(f"استبعدنا {before - len(merged)} صف مكرر (نفس رقم الصفقة)")

    merged.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nتم الحفظ: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
