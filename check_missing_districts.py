"""
يقارن أسماء الأحياء بس (بدون الاعتماد على أعداد districts.csv غير الموثوقة)
بين القائمة الرسمية وبين الأحياء اللي فعليًا ظهرت ببياناتنا (active_ids_today.csv)
-- يحدد أي حي مفقود بالكامل (صفر إعلانات عندنا منه).
"""

import pandas as pd
import os
from urllib.parse import unquote

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ACTIVE_IDS_PATH = os.path.join(DATA_DIR, "active_ids_today.csv")
DISTRICTS_REFERENCE_PATH = os.path.join(DATA_DIR, "districts.csv")

BASE_URL = "https://sa.aqar.fm"


def parse_district_from_url(url):
    path = unquote(str(url).replace(BASE_URL, "")).strip("/")
    parts = path.split("/")
    if len(parts) > 3 and parts[3].startswith("حي"):
        return parts[3].replace("-", " ")
    return None


def main():
    if not os.path.exists(ACTIVE_IDS_PATH):
        print(f"تحذير: ما لقيت {ACTIVE_IDS_PATH} -- شغّل crawl_active_ids.py أول")
        return
    if not os.path.exists(DISTRICTS_REFERENCE_PATH):
        print(f"تحذير: ما لقيت {DISTRICTS_REFERENCE_PATH}")
        return

    active = pd.read_csv(ACTIVE_IDS_PATH, encoding="utf-8-sig")
    active["district"] = active["url"].apply(parse_district_from_url)
    our_districts = set(active["district"].dropna())
    our_counts = active["district"].value_counts().to_dict()

    reference = pd.read_csv(DISTRICTS_REFERENCE_PATH, encoding="utf-8-sig")
    official_districts = set(reference["name"])

    missing = official_districts - our_districts
    covered = official_districts & our_districts
    extra = our_districts - official_districts  # عندنا بيانات لحي مو بالقائمة الرسمية (نادر)

    print(f"إجمالي الأحياء بالقائمة الرسمية: {len(official_districts)}")
    print(f"أحياء ظهرت ببياناتنا (بأي عدد): {len(covered)}")
    print(f"أحياء مفقودة بالكامل (صفر إعلان عندنا): {len(missing)}")
    if extra:
        print(f"أحياء عندنا مو بالقائمة الرسمية: {len(extra)}")

    if missing:
        print("\n--- الأحياء المفقودة بالكامل ---")
        for name in sorted(missing):
            print(f"  - {name}")

    if extra:
        print("\n--- أحياء عندنا زيادة (تحقق من تطابق الاسم) ---")
        for name in sorted(extra):
            print(f"  - {name} ({our_counts.get(name, 0)} إعلان)")

    # نحفظ قائمة الأحياء المفقودة عشان نستخدمها لاحقًا (نبحث لها روابط يدويًا لو احتجنا)
    out_path = os.path.join(DATA_DIR, "missing_districts.csv")
    pd.DataFrame({"district_name": sorted(missing)}).to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nتم حفظ قائمة الأحياء المفقودة: {out_path}")


if __name__ == "__main__":
    main()
