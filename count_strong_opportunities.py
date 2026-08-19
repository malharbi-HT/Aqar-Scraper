"""
يحسب عدد "الفرص القوية" الحالية من الملف الشامل (yield_from_sakani_indicators.csv)،
مو من عيّنة العرض المصغّرة (manager_presentation_report.csv اللي فيها 20 عقار بس).

المعيار: عائد >= 7% (بغض النظر عن درجة ثقة سكني -- كل العقارات المؤهلة).
"""

import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INPUT_PATH = os.path.join(DATA_DIR, "yield_from_sakani_indicators.csv")

STRONG_YIELD_THRESHOLD = 5.0


def main():
    if not os.path.exists(INPUT_PATH):
        print(f"تحذير: ما لقيت {INPUT_PATH}")
        return

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    print(f"إجمالي العقارات المحسوبة (لها عائد من مؤشرات سكني): {len(df)}")

    strong = df[df["expected_yield_pct_sakani"] >= STRONG_YIELD_THRESHOLD]
    print(f"\nعدد الفرص القوية (عائد >= {STRONG_YIELD_THRESHOLD}%): {len(strong)}")

    trusted_strong = strong[strong["sakani_trusted"] == True]
    print(f"منها بثقة عالية (sakani_trusted=True): {len(trusted_strong)}")

    print(f"\n--- توزيع الفرص القوية حسب المنطقة ---")
    print(strong["direction"].value_counts().to_string())

    print(f"\n--- توزيع الفرص القوية حسب الحي (أعلى 10) ---")
    print(strong["district"].value_counts().head(10).to_string())

    if "verdict_price" in strong.columns:
        print(f"\n--- منها كمان بسعر بيع عادل (verdict_price = سعر عادل) ---")
        fair_price = strong[strong["verdict_price"].astype(str).str.contains("عادل", na=False)]
        print(f"عدد: {len(fair_price)}")


if __name__ == "__main__":
    main()
