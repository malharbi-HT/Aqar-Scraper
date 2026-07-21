# Aqar.fm Scraper

سحب تلقائي يومي لبيانات إعلانات العقارات من sa.aqar.fm عبر GitHub Actions.

## طريقة التشغيل

### 1. تجربة محلية أولاً (مهم جدًا قبل رفع المشروع)
```bash
pip install -r requirements.txt
python scraper.py
```
راقب الـ output بالتيرمنال — لو لقيت الحقول (خصوصًا `latitude`/`longitude`/`images`) طالعة فاضية لعدد كبير من الإعلانات، فهذا معناه إن الموقع ما يستخدم __NEXT_DATA__ بالشكل المتوقع، وبنحتاج نفتح صفحة إعلان بالمتصفح (F12 > View Source) ونشوف وين البيانات فعليًا مخبوءة ونعدل دالة `scrape_listing_detail`.

### 2. رفعه على GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin <رابط الريبو حقك>
git push -u origin main
```

### 3. الجدولة تشتغل تلقائيًا
بمجرد الرفع، GitHub Actions بيشغل السكربت يوميًا الساعة 9 صباحًا (توقيت السعودية) ويحفظ البيانات الجديدة بملف `data/listings.csv`.

تقدر كمان تشغله يدويًا من تبويب **Actions** بصفحة الريبو > اختر workflow > **Run workflow**.

## تعديل نطاق السحب
عدّل قائمة `LIST_PAGES` و `MAX_PAGES_PER_CATEGORY` بأعلى ملف `scraper.py` لإضافة مدن/تصنيفات أخرى (فلل، أراضي، إيجار...).

## ملاحظة مهمة
هذا السكربت يتجنب صراحة كل المسارات المحظورة بـ robots.txt الخاص بالموقع (تواصل المعلنين، تسجيل الدخول، الخرائط الداخلية...). راجع `FORBIDDEN_PATH_PREFIXES` بالكود.
