"""
يستخرج عدد الغرف وعدد دورات المياه من نص الوصف -- يُستخدم كتصحيح احتياطي
لما الحقل الأصلي بالموقع يكون فاضي أو صفر بالغلط (نفس نمط مشاكل المساحة والسعر).
"""

import re

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(text):
    return str(text or "").translate(ARABIC_DIGITS)


# تطبيع الكلمات المركبة (تثنية/جمع) لصيغة "رقم + كلمة مفردة" عشان نلقطها برقم بسيط بعدين
# لاحظ: الترتيب مهم -- الأطول والأكثر تحديدًا أول، عشان ما "دورتين" تتحول جزئيًا بالغلط
NORMALIZATION_MAP = [
    (r"دورتين", "2 دورة"),
    (r"حمامين", "2 حمام"),
    (r"غرفتين", "2 غرفة"),
    (r"ثلاث(?:ة)?\s*دورات", "3 دورة"),
    (r"أربع(?:ة)?\s*دورات", "4 دورة"),
    (r"خمس(?:ة)?\s*دورات", "5 دورة"),
    (r"ست(?:ة)?\s*دورات", "6 دورة"),
    (r"ثلاث(?:ة)?\s*غرف", "3 غرفة"),
    (r"أربع(?:ة)?\s*غرف", "4 غرفة"),
    (r"خمس(?:ة)?\s*غرف", "5 غرفة"),
    (r"ست(?:ة)?\s*غرف", "6 غرفة"),
]


def _normalize_text(description):
    desc = normalize_digits(description)
    for pattern, replacement in NORMALIZATION_MAP:
        desc = re.sub(pattern, replacement, desc)
    return desc


def _extract_count(description, keyword_pattern):
    """بعد التطبيع، يدور على 'رقم + كلمة مفتاحية' أو 'كلمة مفتاحية + رقم' (يدعم الأقواس)"""
    desc = _normalize_text(description)

    m = re.search(rf"(\d{{1,2}})\s*(?:{keyword_pattern})", desc)
    if m:
        return int(m.group(1))
    m = re.search(rf"(?:{keyword_pattern})\s*[:\s(]*(\d{{1,2}})\)?", desc)
    if m:
        return int(m.group(1))
    return None


def extract_bathrooms_from_description(description):
    """يستخرج عدد دورات المياه/الحمامات من الوصف"""
    return _extract_count(description, r"دورة\s*(?:ال)?مياه|دورات\s*(?:ال)?مياه|حمام\s|حمامات")


def extract_rooms_from_description(description):
    """يستخرج عدد غرف النوم من الوصف"""
    desc = _normalize_text(description)
    desc = re.sub(r"غرفة\s*(?:ال)?نوم\s*واحدة", "1 غرفة نوم", desc)
    result = _extract_count(desc, r"غرف\s*(?:ال)?نوم|غرفة\s*(?:ال)?نوم")
    if result is not None:
        return result
    # نمط احتياطي: "عدد الغرف" العام بدون اشتراط كلمة "نوم" بعدها
    return _extract_count(desc, r"عدد\s*الغرف|الغرف")
