#!/usr/bin/env python3
"""
يجمع بيانات بيع الرياض (كل الأنواع) ويفحص روابط عقار: شغال / محذوف.

الاستخدام:
  pip install pandas requests
  python riyadh_sale_merge_and_check.py                 # جمع + فحص كل الروابط
  python riyadh_sale_merge_and_check.py --limit 200     # تجربة على 200 رابط
  python riyadh_sale_merge_and_check.py --skip-check    # جمع فقط
  python riyadh_sale_merge_and_check.py --workers 8     # عدد الطلبات المتوازية

المخرجات:
  riyadh_sale_all_types.csv        الملف المجمع
  riyadh_sale_checked.csv          نفس الملف + link_status + http_code
  riyadh_sale_live_only.csv        الإعلانات الشغالة (شغال)
  riyadh_sale_clean.csv            الملف النهائي: بعد حذف ملغي/مغلق/محذوف/غير متوفر
                                   (يبقى شغال + تعذر التحقق)
  riyadh_sale_cancelled.csv        الإعلانات اللي انحذفت من النهائي (نسخة احتياطية)
  riyadh_sale_unverified.csv       تعذر التحقق (ما يعني ملغي، يُعاد فحصه)
يمكن إيقاف السكربت وإعادة تشغيله، يكمل من حيث وقف (checkpoint).
"""
import argparse
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

RAW = "https://raw.githubusercontent.com/malharbi-HT/Aqar-Scraper/main/data"
SOURCES = [  # (ملف, نوع العقار)
    ("listings_sale_normal.csv", "شقة"),
    ("listings_villa.csv", "فيلا"),
    ("listings_floor.csv", "دور"),
    ("listings_land.csv", "أرض"),
    ("listings_building.csv", "عمارة"),
    ("listings_office.csv", "مكتب"),
]
MERGED = "riyadh_sale_all_types.csv"
CHECKED = "riyadh_sale_checked.csv"
LIVE = "riyadh_sale_live_only.csv"
CLEAN = "riyadh_sale_clean.csv"                 # النهائي: بدون الملغاة
CANCELLED = "riyadh_sale_cancelled.csv"      # المحذوفة (نسخة احتياطية)
UNVERIFIED_FILE = "riyadh_sale_unverified.csv"  # يُعاد فحصه
PROGRESS = "riyadh_sale_check_progress.csv"

# عبارات توضح حالة الإعلان (بالترتيب: الأدق أولًا)
STATUS_HINTS = [
    ("ملغي",       ["الإعلان ملغي", "الاعلان ملغي", "إعلان ملغي", "تم إلغاء الإعلان", "تم الغاء الاعلان", "أُلغي الإعلان"]),
    ("محذوف",      ["الإعلان محذوف", "الاعلان محذوف", "تم حذف الإعلان", "تم حذف الاعلان", "إعلان محذوف"]),
    ("مغلق",       ["الإعلان مغلق", "الاعلان مغلق", "إعلان مغلق", "الإعلان منتهي", "الاعلان منتهي", "انتهى الإعلان", "انتهى الاعلان", "إعلان منتهي"]),
    ("غير متوفر",  ["الإعلان غير موجود", "الاعلان غير موجود", "الإعلان غير متوفر", "الاعلان غير متوفر",
                   "هذا الإعلان لم يعد", "الصفحة غير موجودة"]),
]
ACTIVE = "شغال"
UNVERIFIED = "تعذر التحقق"
CANCELLED_SET = {"ملغي", "مغلق", "محذوف", "غير متوفر"}   # تروح تبويب «الملغاه»
LOGIN_HINTS = ["/login", "/signin", "/auth", "تسجيل الدخول"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# ---------------------------------------------------------------- الجمع
def load_source(name, ptype):
    local = os.path.join("data", name)
    src = local if os.path.exists(local) else f"{RAW}/{name}"
    print(f"  قراءة {name}  ({'محلي' if src == local else 'GitHub'})")
    df = pd.read_csv(src, encoding="utf-8-sig", low_memory=False)
    df.insert(0, "property_type", ptype)
    return df


def merge():
    parts = [load_source(n, t) for n, t in SOURCES]
    df = pd.concat(parts, ignore_index=True)
    before = len(df)
    df = df.drop_duplicates("listing_id")
    print(f"المجموع: {len(df):,} إعلان (شلت {before - len(df):,} مكرر)")
    print(df["property_type"].value_counts().to_string())
    df.to_csv(MERGED, index=False, encoding="utf-8-sig")
    return df


# ---------------------------------------------------------------- الفحص
class Limiter:
    """حد أدنى للفاصل بين الطلبات حتى ما يحظرنا الموقع."""
    def __init__(self, per_sec):
        self.gap = 1.0 / per_sec
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            t = max(now, self.next)
            self.next = t + self.gap
        if t > now:
            time.sleep(t - now)


def classify_body(body):
    for status, phrases in STATUS_HINTS:
        if any(ph in body for ph in phrases):
            return status
    return None


def check_one(session, url, limiter, retries=3):
    """يرجع (الحالة, كود HTTP).
    الحالات: شغال | ملغي | مغلق | محذوف | غير متوفر | تعذر التحقق"""
    code = None
    for attempt in range(retries):
        limiter.wait()
        try:
            r = session.get(url, timeout=25, allow_redirects=True)
            code = r.status_code
            if code in (401, 403, 429, 503):      # حظر أو تسجيل دخول: أعد المحاولة
                time.sleep(5 * (attempt + 1))
                continue
            if code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            if code in (404, 410):
                return (classify_body(r.text) or "غير متوفر"), code
            if code == 200:
                final = r.url.split("?")[0]
                if any(h in final for h in LOGIN_HINTS[:3]):
                    return UNVERIFIED, code        # طلب تسجيل دخول
                found = classify_body(r.text)
                if found:
                    return found, code
                # تحويل إلى صفحة قائمة (بدون رقم الإعلان) = غير متوفر
                want = re.search(r"(\d{5,})/?$", url)
                got = re.search(r"(\d{5,})/?$", final)
                if want and (not got or got.group(1) != want.group(1)):
                    return "غير متوفر", code
                if len(r.text) < 5000:
                    return UNVERIFIED, code        # صفحة فاضية: ما نحكم عليها
                return ACTIVE, code
            return UNVERIFIED, code
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    return UNVERIFIED, code


def run_check(df, workers, rate, limit):
    done = {}
    if os.path.exists(PROGRESS):
        p = pd.read_csv(PROGRESS, dtype=str)
        # «تعذر التحقق» يُعاد فحصه دائمًا ولا يُحكم عليه بأنه ملغي
        p = p[p["link_status"] != UNVERIFIED]
        done = dict(zip(p["listing_id"], zip(p["link_status"], p["http_code"])))
        print(f"استئناف: {len(done):,} رابط منفحص سابقًا")

    todo = df[~df["listing_id"].astype(str).isin(done)]
    if limit:
        todo = todo.head(limit)
    print(f"للفحص الآن: {len(todo):,} رابط  (workers={workers}, rate={rate}/s)")

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "ar,en;q=0.8"})
    limiter = Limiter(rate)
    results = {}
    t0 = time.time()
    save_every = 200

    def flush():
        rows = [(k, v[0], v[1]) for k, v in {**done, **results}.items()]
        pd.DataFrame(rows, columns=["listing_id", "link_status", "http_code"]) \
          .to_csv(PROGRESS, index=False)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(check_one, session, row.url, limiter): str(row.listing_id)
                for row in todo.itertuples()}
        try:
            for i, f in enumerate(as_completed(futs), 1):
                results[futs[f]] = f.result()
                if i % save_every == 0:
                    flush()
                    el = time.time() - t0
                    print(f"  {i:,}/{len(futs):,}  ({i/el:.1f} رابط/ث)", flush=True)
        except KeyboardInterrupt:
            print("\nتوقف يدوي، أحفظ التقدم...")
            for f in futs:
                f.cancel()
    flush()

    allres = {**done, **results}
    df = df.copy()
    df["link_status"] = df["listing_id"].astype(str).map(lambda k: allres.get(k, ("لم يُفحص", ""))[0])
    df["http_code"] = df["listing_id"].astype(str).map(lambda k: allres.get(k, ("", ""))[1])
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-check", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="فحص أول N رابط فقط (تجربة)")
    ap.add_argument("--force-delete", action="store_true", help="احذف حتى لو نسبة الملغاة عالية")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--rate", type=float, default=5.0, help="طلبات بالثانية كحد أقصى")
    a = ap.parse_args()

    print("== الجمع ==")
    df = merge()
    if a.skip_check:
        return

    print("\n== فحص الروابط ==")
    out = run_check(df, a.workers, a.rate, a.limit)
    out.to_csv(CHECKED, index=False, encoding="utf-8-sig")
    out[out["link_status"] == ACTIVE].to_csv(LIVE, index=False, encoding="utf-8-sig")
    gone = out["link_status"].isin(CANCELLED_SET)
    # حماية: لو أغلب الروابط طلعت ملغاة غالبًا فيه مشكلة (حظر/تغيّر الموقع) فلا نحذف
    if len(out) and gone.mean() > 0.6 and not a.force_delete:
        print(f"\n⚠ {gone.mean():.0%} من الروابط طلعت ملغاة، غير طبيعي. ما حذفت شيء. "
              f"راجع الفحص أو أعد التشغيل مع --force-delete.")
    else:
        out[~gone].drop(columns=["http_code"]).to_csv(CLEAN, index=False, encoding="utf-8-sig")
        print(f"\nحذفت {gone.sum():,} إعلان ملغي -> الملف النهائي: {CLEAN} ({(~gone).sum():,} إعلان)")
    out[out["link_status"].isin(CANCELLED_SET)].to_csv(CANCELLED, index=False, encoding="utf-8-sig")
    out[out["link_status"] == UNVERIFIED].to_csv(UNVERIFIED_FILE, index=False, encoding="utf-8-sig")

    print("\nالنتيجة:")
    print(out["link_status"].value_counts().to_string())
    print(pd.crosstab(out["property_type"], out["link_status"]).to_string())
    n = (out["link_status"] == UNVERIFIED).sum()
    if n:
        print(f"\n{n:,} رابط «تعذر التحقق»: ما يعني أنه ملغي. أعد تشغيل السكربت "
              f"لإعادة فحصه قبل نقله إلى «الملغاه»، أو قلل --rate.")


if __name__ == "__main__":
    sys.exit(main())
