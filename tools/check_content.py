#!/usr/bin/env python3
"""
مدقّق المحتوى — القسم 5.2 · العقد في controls/schema.json
=========================================================

يفحص كل مقال قبل البناء ويفشل قبل أن يُنشر شيء ناقص.

لماذا الرسائل بالعربية
----------------------
الكاتب غير تقني، وهو **من يقرأ هذه الرسائل** لا المطوّر. رسالة مثل
`ValidationError: title length 8 < 10` تجعله يتصل بالمالك؛ ورسالة «العنوان
يجب أن يكون بين 10 و70 محرفًا، وعنوانك 8» يصلحها بنفسه في دقيقة.

القسم 14.2: أي حالة يمكن للكاتب إصلاحها بنفسه ← رسالة بلغته وخطوة تالية
واضحة. أي حالة تقنية ← طمأنة وتصعيد للمالك.

لماذا لا يُكرَّر المخطط هنا
---------------------------
كل حد وكل قيد يُقرأ من `controls/schema.json`. تكرارها في السكربت يعني
انحرافًا صامتًا بين ما يتحقّق منه البناء وما تعرضه اللوحة للكاتب — وهو
بالضبط العيب الذي وُضع القسم 16 لمنعه.

الاستخدام:
    python3 tools/check_content.py <مجلد المحتوى>
    python3 tools/check_content.py content --json    # مخرجات للأتمتة
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(ROOT, "controls", "schema.json")

IMAGE_EXT = None          # يُملأ من المخطط
FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def load_schema():
    with open(SCHEMA, encoding="utf-8") as fh:
        return json.load(fh)


def parse_front_matter(text):
    """YAML مبسّط: يكفي لما يسمح به المخطط (نص، تاريخ، منطقي، لائحة)."""
    m = FRONT.match(text)
    if not m:
        return None, text
    data, block = {}, m.group(1)
    key = None
    for raw in block.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("-") and key:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(line.lstrip()[1:].strip().strip('"\''))
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            data[key] = [x.strip().strip('"\'') for x in inner.split(",") if x.strip()] if inner else []
        elif val in ("true", "false"):
            data[key] = val == "true"
        elif val == "":
            data[key] = []
        else:
            data[key] = val.strip('"\'')
    return data, text[m.end():]


def visible_length(value):
    """طول العنوان كما يراه القارئ — لا نحسب مسافات الأطراف."""
    return len(str(value).strip())


def display(path):
    """مسار قصير مقروء. المحتوى قد يُمرَّر من خارج المستودع (سير العمل
    يستنسخه في مجلد مؤقت)، فلا نفترض أنه تحته."""
    full = os.path.abspath(path)
    return os.path.relpath(full, ROOT) if full.startswith(ROOT + os.sep) else full


# ── ما يحجز المقال وما يُنبّه الكاتب فقط (2026-11) ─────────────────────
#
# حتى نوفمبر 2026 كان كل بند هنا يوقف نشر المدونة كلها: الكلمة المفتاحية
# إلزامية، وطول العنوان والوصف حدّ صارم. فصارت بنود «جودة السيو» اقتراحًا
# للكاتب يظهر في «بلاغات النشر» والمقال منشور: حدود الطول في كل حقل عليه
# "advisory_length" في المخطط (العنوان، وعنوان محركات البحث، والوصف،
# والكلمة)، وكل ما يخص الكلمة المفتاحية. ويبقى حاجزًا ما يكسر الصفحة نفسها:
# حقل إلزامي فارغ، رابط غير صالح، تاريخ غير مفهوم، صورة مفقودة، عناوين تُسقط
# القالب، مقال فارغ. والحاجز يحجز **مقاله وحده** (tools/build_blog.py).
#
# نُقل من مدونة zero2one.sa بقرار المالك (2026-11-14).


def check_file(path, schema, problems, warnings=None):
    """``warnings``: إن مُرّرت قائمة جُمعت فيها الاقتراحات (لا تحجز)؛ وإلا أُهملت."""
    rel = display(path)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    fm, body = parse_front_matter(text)

    def bad(msg):
        problems.append((rel, msg))

    def soft(msg):
        if warnings is not None:
            warnings.append((rel, msg))

    if fm is None:
        bad("الملف لا يبدأ بكتلة إعدادات بين سطري ---. أعد حفظه من اللوحة.")
        return

    # `_index` صفحة قسم لا مقال — هي عنوان المدونة ووصفها، بلا تصنيف
    # ولا صورة مشاركة ولا جسم. مطالبتها بحقول المقال خطأ في المدقّق لا
    # في المحتوى، وكان سيمنع كل بناء.
    if os.path.basename(path).startswith("_index."):
        for name in ("title", "description"):
            rule = schema["fields"].get(name, {})
            val = fm.get(name)
            if not val:
                bad(f"صفحة القسم تحتاج «{name}».")
                continue
            n = visible_length(val)
            lo, hi = rule.get("min_length"), rule.get("max_length")
            if (lo and n < lo) or (hi and n > hi):
                bad((rule.get("error_ar") or "").replace("{actual}", str(n)))
        return

    fields = schema["fields"]
    # قيمة التصنيف في front matter هي slug ثابتة لا الاسم المعروض. هكذا
    # يرتبط المقال العربي والإنجليزي بصفحة أرشيف واحدة مترجمة، ولا يتغيّر
    # الرابط عند تحسين الصياغة المعروضة في schema.json.
    allowed_cats = {c["slug"] for c in schema["categories"]["items"]}

    for name, rule in fields.items():
        val = fm.get(name)
        missing = val is None or (isinstance(val, (str, list)) and len(val) == 0)

        if missing:
            if rule.get("required") and not rule.get("auto"):
                # الحقل غائب، فطوله صفر — وإلا ظهر {actual} حرفيًّا للكاتب
                bad((rule.get("error_ar") or f"الحقل «{name}» مطلوب وهو فارغ.")
                    .replace("{actual}", "0"))
            continue

        if rule["type"] == "string":
            n = visible_length(val)
            lo, hi = rule.get("min_length"), rule.get("max_length")
            if (lo and n < lo) or (hi and n > hi):
                (soft if rule.get("advisory_length") else bad)(
                    (rule.get("error_ar") or f"«{name}» خارج الحدود المسموحة.")
                    .replace("{actual}", str(n)))
            pat = rule.get("pattern")
            if pat and not re.match(pat, str(val)):
                bad(rule.get("error_ar") or f"«{name}» لا يطابق الصيغة المطلوبة.")

        elif rule["type"] == "date":
            # Hugo يرفض تاريخًا بلا ثوانٍ أو منطقة زمنية ويُسقط البناء كله
            # برسالة إنجليزية لا يفهمها الكاتب. أُمسكها هنا برسالة بلغته.
            raw = str(val).strip().strip('"\'')
            import datetime as _dt
            # التحقّق بالتحليل لا بتفتيش النصّ. الشرط القديم كان يبحث عن «+»
            # ليتأكّد من وجود منطقة زمنية، فيرفض كل إزاحة سالبة — و
            # 2026-09-08T08:21:00-07:00 صيغة ISO سليمة يقبلها Hugo. أوقف ذلك
            # النشر في 2026-09-08 حين كتبت اللوحة منطقة متصفّح الكاتب.
            # tzinfo هو الشرط الحقيقي، والباقي يتكفّل به fromisoformat.
            moment = None
            try:
                moment = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                moment = None
            if moment is None:
                bad(f"التاريخ «{raw}» ليس تاريخًا صالحًا. "
                    "الصيغة الصحيحة مثل 2026-08-07T20:22:00+03:00 — "
                    "أعد اختياره من التقويم في اللوحة.")
            elif moment.tzinfo is None:
                moment = None
                bad(f"التاريخ «{raw}» بلا منطقة زمنية. "
                    "الصيغة الصحيحة مثل 2026-08-07T20:22:00+03:00 — "
                    "أعد اختياره من التقويم في اللوحة.")

            # تاريخ في المستقبل = مقال يختفي بلا رسالة. Hugo يستبعده
            # (buildFuture غير مفعّل ولا --buildFuture في build.yml)، والبناء
            # ينجح ويُنشر، فيرى الكاتب «تم النشر» ولا يجد مقاله. ولا بناء
            # مجدولًا يلتقطه بعد مرور الموعد: build.yml يعمل بـ
            # workflow_dispatch وحده. فالمقال لا يظهر أبدًا ما لم يُنشر ثانية.
            # انحراف الساعة أو المنطقة الزمنية يصحّحه tools/prepare_content.py
            # قبل هذا الفحص، وحدّه هناك 24 ساعة. فالعتبة هنا هي العتبة نفسها
            # كي يتّفق المكوّنان بالبناء لا بالمصادفة: ما دون اليوم يُصحَّح
            # صامتًا مع إعلان في السجلّ، وما فوقه خطأ تاريخ حقيقي — سنة أو
            # شهر خاطئ — يستحق عين إنسان. ولو ضاقت العتبة هنا وحدها لظهرت
            # للكاتب رسالة تنفي ما يفعله الأنبوب فعلًا.
            if moment is not None and not fm.get("draft"):
                skew = moment - _dt.datetime.now(_dt.timezone.utc)
                if skew > _dt.timedelta(hours=24):
                    bad(f"تاريخ النشر «{raw}» في المستقبل بأكثر من يوم "
                        f"({skew.days} يومًا)، والمقال لن يظهر في الموقع "
                        "إطلاقًا. تأكّد من السنة والشهر في التقويم داخل اللوحة.")

        elif rule["type"] == "list":
            if len(val) < rule.get("min_items", 0):
                bad(rule.get("error_ar") or f"«{name}» يحتاج عنصرًا واحدًا على الأقل.")
            if name == "categories":
                for c in val:
                    if c not in allowed_cats:
                        choices = "، ".join(sorted(allowed_cats))
                        bad(f"التصنيف «{c}» غير معروف. اختر من القائمة في اللوحة "
                            f"(القيم المسموحة: {choices}).")

        elif rule["type"] == "path" and rule.get("must_be_in_bundle"):
            if "/" in str(val) or str(val).startswith("http"):
                bad("صورة المشاركة يجب أن تكون داخل مجلد المقال نفسه، "
                    "لا رابطًا خارجيًّا ولا مسارًا في مجلد آخر.")
            elif not os.path.exists(os.path.join(os.path.dirname(path), str(val))):
                bad(f"لم أجد الصورة «{val}» في مجلد المقال. ارفعها من اللوحة.")

    # جسم فارغ يمرّ من كل الفحوص أعلاه ويُنتج صفحة بيضاء
    if len(body.strip()) < 200 and not fm.get("draft"):
        bad("المقال شبه فارغ. اكتب المحتوى أو أعده مسودة قبل النشر.")

    if not fm.get("draft"):
        for note in keyword_notes(fm, body):
            soft(note)

    # ── العناوين ──────────────────────────────────────────────────────
    # check_seo.py يرفض عنوانًا فارغًا وقفزة في الدرجات على الصفحة المبنية،
    # برسالة عن ملف HTML لا يعرف الكاتب صلته بمقاله، وبعد Hugo وبعد كل شيء.
    # القاعدة نفسها هنا تمسكه قبل البناء، باسم الملف ورقم السطر وبلغة الكاتب.
    # (h1 في المتن يُخفَّض في tools/prepare_content.py قبل هذا الفحص.)
    for line_no, line in enumerate(without_code(body).splitlines(), start=1):
        if re.match(r"^#{1,6}\s*$", line):
            bad(f"عنوان فارغ في السطر {line_no} — احذفه أو اكتب نصّه.")
    previous = 1
    for match in re.finditer(r"(?m)^(#{1,6})\s+(\S.*)$", without_code(body)):
        level, heading = len(match.group(1)), match.group(2).strip()
        if level > previous + 1:
            bad(f"«{heading[:40]}» قفزة من عنوان {previous} إلى {level}. "
                f"استعمل «عنوان {previous + 1}» بدلها.")
        previous = level

    check_markdown_images(path, body, bad)


# ── صور داخل النصّ ──────────────────────────────────────────────────
#
# الخطّاف layouts/_default/_markup/render-image.html يُسقط بناء Hugo كلّه
# إن أشارت صورة في النصّ إلى ملف ليس في حزمة المقال. هذا ما أوقف نشر المدونة
# كلها من 11 إلى 14 نوفمبر 2026: مقال «الفرق بين الهجمات الإلكترونية والاختراق
# الأمني» يشير إلى صورتين لم تُرفعا قط. الفحص هنا يمسكه قبل البناء، باسم
# الصورة وبلغة الكاتب، فيُحجز المقال وحده.
#
# المطابقة أبسط من GetMatch في Hugo عن قصد: اسم ملف داخل مجلد المقال.
# ما يفوته هذا الفحص يُسنده بنّاء المدونة إلى مقاله من رسالة Hugo نفسها.
MARKDOWN_IMAGE = re.compile(
    r"!\[[^\]]*\]\(\s*(?:<([^>\n]+)>|([^\s)]+))"
    r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)"
)
FENCED_CODE = re.compile(r"(?ms)^(```|~~~).*?^\1[ \t]*$")
INLINE_CODE = re.compile(r"`[^`\n]*`")


def without_code(body):
    """النصّ وكتل الشيفرة أسطر فارغة: # داخلها تعليق برمجي لا عنوان.

    عدد الأسطر يبقى كما هو كي يطابق رقم السطر في الرسالة ما يراه الكاتب.
    """
    return FENCED_CODE.sub(lambda m: "\n" * m.group(0).count("\n"), body)


def markdown_image_targets(body):
    """وجهات صور Markdown في النص، بلا ما داخل كتل الشيفرة (لا تُعرض صورًا)."""
    text = INLINE_CODE.sub("", FENCED_CODE.sub("", body))
    return [m.group(1) or m.group(2) for m in MARKDOWN_IMAGE.finditer(text)]


def check_markdown_images(path, body, bad):
    from urllib.parse import unquote
    bundle = os.path.dirname(path)
    for target in markdown_image_targets(body):
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("//"):
            bad(f"الصورة «{target[:80]}» داخل النصّ رابط خارجي. احذفها وأدرجها من "
                "زرّ الصورة في المحرر لتُحفظ داخل مجلد المقال.")
        elif (target.startswith(("/", "./", "../")) or "\\" in target
              or ".." in target.split("/")):
            bad(f"مسار الصورة «{target[:80]}» داخل النصّ غير صالح. احذفها وأعد "
                "إدراجها من زرّ الصورة في المحرر.")
        elif not (os.path.isfile(os.path.join(bundle, target))
                  or os.path.isfile(os.path.join(bundle, unquote(target)))):
            bad(f"الصورة «{target[:80]}» داخل النصّ غير موجودة في مجلد المقال — "
                "لم تُرفع مع المقال. أعد رفعها من زرّ الصورة في المحرر، أو احذفها من النص، ثم احفظ.")


def check_images(directory, schema, problems):
    cap = schema["bundle"]["max_image_bytes"]
    allowed = set(schema["bundle"]["image_formats"])
    name_re = re.compile(schema["filenames"]["pattern"])
    for base, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            # `_index.<lang>.md` أسماء محجوزة في Hugo، وقاعدة التسمية
            # موجّهة لما يرفعه الكاتب لا لما يولّده النظام
            if f.startswith(".") or f.startswith("_index."):
                continue
            ext = f.rsplit(".", 1)[-1].lower()
            full = os.path.join(base, f)
            rel = display(full)
            if not name_re.match(f):
                problems.append((rel, schema["filenames"]["error_ar"].replace("{name}", f)))
            if ext in allowed:
                size = os.path.getsize(os.path.join(base, f))
                if size > cap:
                    problems.append((rel, schema["bundle"]["max_image_error_ar"]
                                     .replace("{name}", f)
                                     .replace("{actual}", f"{size/1024:.0f} كيلوبايت")))


# ── الكلمة المفتاحية ────────────────────────────────────────────────────
# التطبيع شرط لا ترف: «استعادة البيانات» و«إستعادة البيانات» استعلام واحد عند
# القارئ، والفرق همزةُ وصلٍ لا يراها. وبلا تطبيع يفشل كل تطابق تقريبًا فتصير
# الميزة إزعاجًا يتجاهله الكاتب.
ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
NON_WORD = re.compile(r"[^\w\u0600-\u06FF]+", re.U)


def normalize_keyword(value):
    """يوحّد النصّ للمقارنة: تشكيل، وألف، وياء، وتاء مربوطة، وفراغات."""
    text = ARABIC_DIACRITICS.sub("", str(value)).casefold()
    for source, target in (("أإآٱ", "ا"), ("ى", "ي"), ("ة", "ه"), ("ؤ", "و"), ("ئ", "ي")):
        for ch in source:
            text = text.replace(ch, target)
    return NON_WORD.sub(" ", text).strip()


def keyword_in(haystack, keyword):
    return keyword and keyword in normalize_keyword(haystack)


def keyword_notes(fm, body):
    """اقتراحات الكلمة المفتاحية لملف واحد. لا تحجز شيئًا.

    حتى نوفمبر 2026 كان الحقل إلزاميًّا وفراغه يوقف النشر. صار اختياريًّا،
    وما يخصّه كله إرشاد: غيابها عن العنوان أو الوصف أو الفقرة الأولى أو
    العناوين الفرعية، وكثافة تتجاوز 3% وهي حدّ الحشو المتعارف عليه. أحكام
    تحريرية يقدّرها الكاتب بسياق مقاله.
    """
    raw = str(fm.get("focus_keyword") or "").strip()
    if not raw:
        return []
    key = normalize_keyword(raw)
    notes = []
    where = []
    if not keyword_in(fm.get("title", ""), key):
        where.append("العنوان")
    if not keyword_in(fm.get("description", ""), key):
        where.append("الوصف")
    paragraphs = [p for p in body.strip().split("\n\n") if p.strip()]
    if not (paragraphs and keyword_in(paragraphs[0], key)):
        where.append("الفقرة الأولى")
    headings = " ".join(re.findall(r"^##+\s+(.*)$", body, re.M))
    if not keyword_in(headings, key):
        where.append("العناوين الفرعية")
    if where:
        notes.append(f"الكلمة المفتاحية «{raw}» غائبة عن " + " و".join(where)
                     + ". يُستحسن ذكرها فيها.")

    words = normalize_keyword(body).split()
    span = len(key.split())
    if words and span:
        hits = sum(1 for i in range(len(words) - span + 1)
                   if " ".join(words[i:i + span]) == key)
        density = hits * span / len(words) * 100
        if density > 3:
            notes.append(f"كثافة «{raw}» {density:.1f}% وهي فوق حدّ الحشو 3% — "
                         "جوجل قد يقرؤها تلاعبًا. خفّف تكرارها.")
    return notes


def keyword_duplicates(directory):
    """(ملف، رسالة) لكل كلمة مفتاحية يستهدفها مقالان منشوران بلغة واحدة.

    التنافس الداخلي (cannibalization) ضرر حقيقي: مقالان على استعلام واحد
    يتقاسمان إشاراته فيهبطان معًا. لكنه قرار تحريري لا عطل في صفحة، فصار
    اقتراحًا (2026-11) بعد أن كان يوقف النشر. الرسالة تسمّي الطرفين، وتظهر
    على الأحدث منهما ترتيبًا.
    """
    found = []
    seen = {}
    for name, bundle in bundle_dirs(directory):
        for filename in sorted(os.listdir(bundle)):
            if not (filename.startswith("index.") and filename.endswith(".md")):
                continue
            path = os.path.join(bundle, filename)
            with open(path, encoding="utf-8") as handle:
                fm, _ = parse_front_matter(handle.read())
            if fm is None or fm.get("draft") or fm.get("archived"):
                continue
            raw = str(fm.get("focus_keyword") or "").strip()
            if not raw:
                continue
            lang = filename[len("index."):-len(".md")]
            key = normalize_keyword(raw)
            owner = seen.get((lang, key))
            if owner:
                found.append((display(path),
                              f"الكلمة المفتاحية «{raw}» مستهدَفة أيضًا في «{owner}». "
                              "مقالان على استعلام واحد يتنافسان — يُستحسن تغيير كلمة أحدهما."))
            else:
                seen[(lang, key)] = name
    return found


def is_bundle(path):
    return os.path.isdir(path) and any(
        f.startswith("index.") and f.endswith(".md") for f in os.listdir(path))


def bundle_dirs(directory):
    """حزم المقالات في أيّ من التخطيطين.

    مصدر الكاتب يضعها في ``content/blog/<slug>/``، والنسخة المجهّزة للبناء في
    ``content/<slug>/``.
    """
    blog = os.path.join(directory, "blog")
    base = blog if os.path.isdir(blog) and not is_bundle(blog) else directory
    if not os.path.isdir(base):
        return
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name)
        if not name.startswith(".") and is_bundle(path):
            yield name, path


def check_one_bundle_consistency(name, bundle, problems):
    """الـslug والتصنيفات والأرشفة عقد واحد بين ترجمات الحزمة.

    2026-09-06: مقال جديد حمل slug مقال منشور. مرّ من البوّابة، فطمسه Hugo
    فوق المقال القديم على الرابط نفسه بلا تحذير — Hugo لا يُخطئ على تكرار
    الروابط — وسقط البناء أخيرًا عند tools/normalize_sitemaps.py برسالة
    «الخريطة تحوي روابط مكررة» لا تدل على المقال ولا على السبب.
    """
    parent = os.path.dirname(os.path.normpath(bundle))
    siblings = {n for n in os.listdir(parent) if os.path.isdir(os.path.join(parent, n))}
    records = []
    for filename in sorted(os.listdir(bundle)):
        if not (filename.startswith("index.") and filename.endswith(".md")):
            continue
        path = os.path.join(bundle, filename)
        with open(path, encoding="utf-8") as handle:
            fm, _ = parse_front_matter(handle.read())
        if fm is not None:
            records.append((path, fm))
    if not records:
        return
    first_path, first = records[0]
    expected = {
        "slug": first.get("slug"),
        "archived": bool(first.get("archived", False)),
        "categories": sorted(first.get("categories", [])),
    }
    if expected["slug"] != name:
        # لوحة Sveltia تبني مسار الحزمة من الـslug نفسه. فإن كتب الكاتب
        # رابطًا مستعملًا، لا تكتب فوق المقال القديم بل تُلحق «-رقم» باسم
        # المجلد وحده وتترك الحقل كما كُتب — بلا تحذير. هذه بصمة التصادم،
        # ونسمّيه للكاتب بها بدل مطالبته بمطابقة اسم مجلد لا يراه أصلًا.
        stem = re.sub(r"-\d+$", "", name)
        if stem != name and expected["slug"] == stem and stem in siblings:
            problems.append((display(first_path),
                             f"الرابط «{stem}» مستعمل في مقال آخر. "
                             "افتح حقل «الرابط القصير بالإنجليزية» واختر "
                             "رابطًا مختلفًا، ثم احفظ."))
        else:
            problems.append((display(first_path),
                             f"قيمة slug يجب أن تطابق اسم مجلد الحزمة «{name}»."))
    for path, fm in records[1:]:
        actual = {
            "slug": fm.get("slug"),
            "archived": bool(fm.get("archived", False)),
            "categories": sorted(fm.get("categories", [])),
        }
        for field in expected:
            if actual[field] != expected[field]:
                problems.append((display(path),
                                 f"الحقل «{field}» يجب أن يتطابق بين كل ترجمات الحزمة."))


def check_bundle_consistency(directory, problems):
    """على شكلَي المحتوى: مصدر الكاتب (``content/blog/``) والنسخة المجهّزة
    (جذر ``content/``). البحث عن ``blog/`` وحده كان يُخرج الدالة صامتة في CI —
    وهناك بالضبط تُشغَّل — فلم يُفحص هذا العقد ولا مرة حتى 2026-09-07."""
    for name, bundle in bundle_dirs(directory):
        check_one_bundle_consistency(name, bundle, problems)


def check_bundle(bundle, schema, warnings=None):
    """كل فحوص مقال واحد، لبنّاء المدونة: مشكلة في مقال تحجزه هو وحده.

    الفحوص نفسها التي يجريها main() على الشجرة كلها، مقصورةً على الحزمة.
    ``warnings``: قائمة تُجمع فيها الاقتراحات التي لا تحجز. تكرار الكلمة
    المفتاحية بين مقالين يحتاج الشجرة كلها: انظر keyword_duplicates().
    """
    problems = []
    name = os.path.basename(os.path.normpath(bundle))
    for filename in sorted(os.listdir(bundle)):
        if filename.endswith(".md"):
            check_file(os.path.join(bundle, filename), schema, problems, warnings)
    check_one_bundle_consistency(name, bundle, problems)
    check_images(bundle, schema, problems)
    return problems


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    directory = args[0] if args else os.path.join(ROOT, "content")
    as_json = "--json" in sys.argv

    if not os.path.isdir(directory):
        print(f"  لا يوجد مجلد محتوى: {directory}")
        return 1

    schema = load_schema()
    problems = []
    # قناة ثانية إلى جانب problems: اقتراحات تُطبع ولا تُوقف. بلا فصلها كان
    # الخيار الوحيد بين إسقاط البناء وبين الصمت — وأحكام التحرير لا تحتمل
    # الأول ولا تستحق الثاني.
    warnings = []
    count = 0
    for base, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                count += 1
                check_file(os.path.join(base, f), schema, problems, warnings)
    check_bundle_consistency(directory, problems)
    warnings.extend(keyword_duplicates(directory))
    check_images(directory, schema, problems)

    if as_json:
        print(json.dumps([{"file": f, "message": m} for f, m in problems],
                         ensure_ascii=False, indent=2))
        return 1 if problems else 0

    if warnings:
        print(f"  💡 {len(warnings)} اقتراح لا يوقف النشر:")
        for f, m in warnings:
            print(f"     • {f}: {m}")
        print()

    if not problems:
        print(f"  ✅ {count} ملف — لا مشاكل")
        return 0

    print(f"  ❌ {len(problems)} مشكلة في {count} ملف\n")
    last = None
    for f, m in problems:
        if f != last:
            print(f"  ── {f}")
            last = f
        print(f"     • {m}")
    print("\n  البناء متوقّف حتى تُصلَح هذه النقاط.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
