#!/usr/bin/env python3
"""جهّز محتوى Hugo من مستودع التحرير واستبعد الحزم المؤرشفة بالكامل.

وكل تصحيح هنا يجري على النسخة المجهّزة وحدها؛ ملف الكاتب في مستودع المحتوى
لا يتغيّر: التوقيت، والعناوين الرئيسية المكرّرة، وسطر الجدول الفاصل، وأسماء
الملفات.

الاستخدام:
    python3 tools/prepare_content.py <content-source>

الوجهة ثابتة عمدًا: ``content/`` داخل مستودع البناء. هذا يمنع تمرير مسار
خاطئ إلى عملية تنظيف ويجعل الناتج مؤقتًا قابلًا لإعادة التوليد.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from urllib.parse import unquote

from check_content import FRONT, MARKDOWN_IMAGE, parse_front_matter


ROOT = Path(__file__).resolve().parent.parent
DESTINATION = ROOT / "content"
MARKER = ".generated-by-prepare-content"


class PrepareError(RuntimeError):
    pass


class BundleProblem(PrepareError):
    """مشكلة في مقال واحد يصلحها الكاتب، لا في المحتوى كله.

    الرسالة موجّهة للكاتب. في الوضع الصارم (سطر الأوامر والمعاينة) تُرفع
    كما كانت؛ وبنّاء المدونة (tools/build_blog.py) يسجّلها ويحجز المقال وحده.
    """


def reject_symlinks(source: Path) -> None:
    """لا ننشر ملفًا يستطيع الخروج من checkout المحتوى عبر symlink."""
    if source.is_symlink():
        raise PrepareError(f"مجلد المحتوى لا يجوز أن يكون رابطًا رمزيًا: {source}")
    for base, directories, files in os.walk(source, followlinks=False):
        for name in [*directories, *files]:
            path = Path(base) / name
            if path.is_symlink():
                raise PrepareError(f"الرابط الرمزي غير مسموح في المحتوى: {path}")


def front_matter(path: Path) -> dict[str, object]:
    try:
        data, _ = parse_front_matter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise BundleProblem(
            f"تعذّرت قراءة {path.name}. أعد حفظ المقال من اللوحة."
        ) from exc
    if data is None:
        raise BundleProblem(
            f"الملف {path.name} لا يبدأ بكتلة إعدادات بين سطري ---. أعد حفظه من اللوحة."
        )
    return data


def bundle_is_archived(bundle: Path) -> bool:
    indexes = sorted(bundle.glob("index.*.md"))
    if not indexes:
        raise BundleProblem(
            f"مجلد المقال «{bundle.name}» بلا نصّ (index.<lang>.md) — ربما رُفعت "
            "صورة ولم يُحفظ المقال. افتحه من اللوحة واحفظه، أو أبلغ المالك."
        )
    states = {bool(front_matter(path).get("archived", False)) for path in indexes}
    if len(states) != 1:
        raise BundleProblem(
            "مفتاح «أرشفة المقال» مختلف بين ترجمتي المقال. اجعله متطابقًا في "
            "اللغتين ثم احفظ."
        )
    return states == {True}


RIYADH = datetime.timezone(datetime.timedelta(hours=3))
DATE_LINE = re.compile(r'^(?P<key>date|lastmod):[ \t]*(?P<q>["\']?)(?P<val>[^"\'\n]+)(?P=q)[ \t]*$',
                       re.M)
SKEW_LIMIT = datetime.timedelta(hours=24)


def normalize_dates(bundle: Path) -> list[str]:
    """يوحّد تواريخ الحزمة على توقيت الرياض ويصحّح انحراف ساعة الكاتب.

    التاريخ في هذا النظام تُنتجه لوحة Sveltia من ساعة متصفّح الكاتب ومنطقته.
    هذا أوقف النشر أربع مرات بأعراض مختلفة: صيغة بلا ثوانٍ (2026-08-07)، ثم
    إزاحة بلا نقطتين +0300 (2026-08-18 و2026-09-06)، ثم منطقة سالبة -07:00
    مع ساعة متقدّمة سبع ساعات (2026-09-08). العلّة واحدة في كل مرة: لحظة
    النشر تأتي من جهاز لا نتحكّم به، ويحكم عليها فحص هشّ.

    فالعلاج هنا لا هناك. تُحوَّل كل لحظة إلى +03:00 — وهي المنطقة نفسها في
    hugo.toml — فيصير الملف المنشور موحّدًا مهما كان جهاز الكاتب. وإن كانت
    اللحظة في المستقبل بما لا يتجاوز 24 ساعة فهي انحراف ساعة أو منطقة، لا
    جدولة: لا جدولة في هذا النظام أصلًا، فـbuild.yml يعمل بـworkflow_dispatch
    وحده ولا شيء يلتقط المقال بعد مرور موعده. تُضبط على لحظة البناء ويُعلن
    ذلك في السجلّ. وما تجاوز 24 ساعة يُترك ليوقفه check_content: ذاك خطأ
    تاريخ حقيقي يستحق عين إنسان.

    والتعديل يجري على النسخة المجهَّزة لا على مستودع الكاتب، فلا يكتب النظام
    فوق ما كتبه.
    """
    notes: list[str] = []
    now = datetime.datetime.now(RIYADH)
    for path in sorted(bundle.glob("index.*.md")):
        text = path.read_text(encoding="utf-8")
        head_end = text.find("\n---", 4)
        if not text.startswith("---") or head_end == -1:
            continue
        head, rest = text[:head_end], text[head_end:]
        changed = False

        def fix(match: "re.Match[str]") -> str:
            nonlocal changed
            raw = match.group("val").strip()
            try:
                moment = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return match.group(0)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=RIYADH)
            local = moment.astimezone(RIYADH)
            if now < local <= now + SKEW_LIMIT:
                notes.append(f"{bundle.name}/{path.name}: {match.group('key')} كان "
                             f"{local.isoformat()} — أي في المستقبل، فضُبط على لحظة البناء")
                local = now.replace(microsecond=0)
            fixed = local.isoformat()
            if fixed == raw:
                return match.group(0)
            changed = True
            quote = match.group("q") or '"'
            return f'{match.group("key")}: {quote}{fixed}{quote}'

        head = DATE_LINE.sub(fix, head)
        if changed:
            path.write_text(head + rest, encoding="utf-8")
    return notes


ATX_H1 = re.compile(r"^#[ \t]+(?P<text>\S.*?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^[ \t]{0,3}(?:```+|~~~+)")


def _comparable(value: str) -> str:
    """يوحّد العنوان للمقارنة: بلا تشكيل markdown ولا فراغات زائدة."""
    return re.sub(r"[\s*_`~]+", " ", str(value)).strip().casefold()


def demote_body_h1(bundle: Path) -> list[str]:
    """يُصلح عناوين h1 داخل متن المقال، على النسخة المجهَّزة لا على مصدر الكاتب.

    القالب يبني h1 وحيدًا من `title`، فأي h1 في المتن يُنتج عنوانين. يوقف ذلك
    `check_seo.py` ويحجب النشر، ويُنتج صفحة تُربك قارئ الشاشة الذي يتنقّل
    بالعناوين.

    ولا يقع بخطأ الكاتب: لوحة Sveltia لا تعرض زرّ heading-one إطلاقًا
    (`tools/generate_cms.py` يستبعده)، لكن اللصق من Word أو من صفحة ويب يجلب
    العنوان نصًّا مع بقية المقال. حدث في 2026-08-18 وأوقف أول مقال ينشره
    الكاتب بنفسه.

    فالإصلاح هنا بدل ردّ المقال إليه: h1 يكرّر `title` يُحذف لأنه تكرار محض،
    وأي h1 آخر يُخفَّض إلى h2 فيبقى نصّه وموضعه. وما داخل كتل الشيفرة لا
    يُمَسّ — قد يكون `#` تعليقًا في مثال برمجي لا عنوانًا.
    """
    notes: list[str] = []
    for path in sorted(bundle.glob("index.*.md")):
        text = path.read_text(encoding="utf-8")
        try:
            data, body = parse_front_matter(text)
        except Exception:
            continue
        title = _comparable(data.get("title", ""))

        lines = body.split("\n")
        out: list[str] = []
        fenced = False
        removed = demoted = 0
        for line in lines:
            if FENCE.match(line):
                fenced = not fenced
                out.append(line)
                continue
            match = None if fenced else ATX_H1.match(line)
            if match is None:
                out.append(line)
                continue
            if title and _comparable(match.group("text")) == title:
                removed += 1
                # واسحب سطرًا فارغًا تاليًا كي لا يبقى فراغ مزدوج مكان العنوان.
                if out and out[-1].strip() == "":
                    out.pop()
                continue
            out.append("#" + line.lstrip())
            demoted += 1

        if not (removed or demoted):
            continue
        path.write_text(text[: len(text) - len(body)] + "\n".join(out), encoding="utf-8")
        detail = " · ".join(
            part for part in (
                f"حُذف {removed} عنوانًا مكرّرًا للعنوان الرئيسي" if removed else "",
                f"خُفّض {demoted} عنوانًا إلى h2" if demoted else "",
            ) if part
        )
        notes.append(f"{bundle.name}/{path.name}: {detail}")
    return notes


# ── الجداول ────────────────────────────────────────────────────────────
#
# جدول Markdown يحتاج تحت سطر عناوينه سطرًا فاصلًا (| --- | --- |)، وبدونه
# يطبعه Hugo فقرةً من الخطوط العمودية. لوحة الكتابة بلا زرّ جدول، والجداول
# الثلاثة المنشورة حتى 2026-11-14 (حصان طروادة، الفدية في الرياض، الفرق بين
# الهجمات والاختراق) كلها بلا هذا السطر منذ أول حفظ: على الموقع الحي ظهرت
# نصًّا تتخلّله خطوط |.
#
# نضيفه تحت السطر الأول من كل كتلة أسطر تبدأ وتنتهي بـ|، إن تساوى عدد خانات
# سطرَيها الأوّلين (اثنتان فأكثر). ما داخل كتل الشيفرة لا يُمسّ. والإصلاح على
# النسخة المجهّزة وحدها، كالتوقيت؛ نُقل من مدونة zero2one.sa (2026-10-22).
#
# وزيادة هنا لا في الأصل: سطر | وحيد بخانة واحدة يليه جدول (بعد سطر فارغ أو
# أكثر) هو عنوان الجدول — خلية مدموجة فوق الجدول في المستند الذي نُسخ منه.
# مقال «حصان طروادة» فيه «| ملخص أنواع فيروسات حصان طروادة |». يبقى بلا سطر
# فاصل نصًّا بخطّين عموديين فوق جدول سليم، فيصير سطرًا عريضًا بنصّه نفسه.
TABLE_ROW = re.compile(r"^ {0,3}\|.*\|[ \t\r]*$")
TABLE_DELIMITER = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t\r]*$")
CODE_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def table_cells(row: str) -> int:
    return len(UNESCAPED_PIPE.split(row.strip()[1:-1]))


def table_follows(lines: list[str], start: int) -> bool:
    """هل يبدأ جدول حقيقي (سطران فأكثر، خانتان فأكثر) بعد أسطر فارغة من start؟"""
    i = start
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i == start:
        return False
    end = i
    while end < len(lines) and TABLE_ROW.match(lines[end]):
        end += 1
    return end - i >= 2 and table_cells(lines[i]) >= 2


def title_row_text(row: str) -> str:
    """نصّ خانة العنوان بلا خطوطها ولا تعريضها، ليُكتب سطرًا عريضًا واحدًا."""
    text = row.strip()[1:-1].strip()
    if len(text) > 4 and text.startswith("**") and text.endswith("**"):
        text = text[2:-2].strip()
    return text


def repair_tables(index: Path) -> list[dict[str, int]]:
    """يضيف السطر الفاصل لجدول بلا فاصل. يعيد ما أُصلح (السطر وعدد الخانات).

    سطر العنوان المنفرد فوق جدول يُسجَّل بـ ``columns`` = 0.
    """
    text = index.read_text(encoding="utf-8")
    front = FRONT.match(text)
    head, body = (text[:front.end()], text[front.end():]) if front else ("", text)
    offset = head.count("\n")
    lines = body.split("\n")
    out: list[str] = []
    changes: list[dict[str, int]] = []
    fence = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        opening = CODE_FENCE.match(line)
        if fence:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence):
                fence = ""
            out.append(line)
            i += 1
            continue
        if opening:
            fence = opening.group(1)
            out.append(line)
            i += 1
            continue
        end = i
        while end < len(lines) and TABLE_ROW.match(lines[end]):
            end += 1
        block = lines[i:end]
        if (len(block) >= 2 and not TABLE_DELIMITER.match(block[1])
                and table_cells(block[0]) >= 2 and table_cells(block[0]) == table_cells(block[1])):
            columns = table_cells(block[0])
            out.extend([block[0], "|" + " --- |" * columns, *block[1:]])
            changes.append({"line": offset + i + 1, "columns": columns})
            i = end
            continue
        if (len(block) == 1 and table_cells(block[0]) == 1 and title_row_text(block[0])
                and table_follows(lines, end)):
            out.append(f"**{title_row_text(block[0])}**")
            changes.append({"line": offset + i + 1, "columns": 0})
            i = end
            continue
        if block:
            out.extend(block)
            i = end
            continue
        out.append(line)
        i += 1
    if changes:
        index.write_text(head + "\n".join(out), encoding="utf-8")
    return changes


# ── أسماء الملفات ──────────────────────────────────────────────────────
#
# قاعدة الأسماء في controls/schema.json (حروف إنجليزية صغيرة وأرقام وشرطات)
# كانت توقف النشر كله إن خالفها ملف واحد: صورة باسم عربي أو فيه مسافات تحوّلها
# اللوحة أحيانًا إلى «_.webp»، فيقف كل شيء بسبب اسم لا يراه القارئ.
#
# الاسم شأن تقني لا تحريري، فيُصلَح هنا تلقائيًّا: يُعاد تسمية الملف في
# النسخة المجهّزة، وتُحدَّث إشارات المقال إليه (صورة المشاركة وصور النصّ).
# ملف الكاتب في مستودع المحتوى لا يتغيّر. نُقل من مدونة zero2one.sa (2026-11-14).
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")   # = filenames.pattern في المخطط
FEATURED_LINE = re.compile(r"(?m)^(featured_image:[ \t]*)([\"']?)([^\"'\n]*?)\2[ \t]*$")


def safe_name(name: str, taken: set[str]) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    ext = re.sub(r"[^a-z0-9]", "", ext.lower())[:10]
    stem = re.sub(r"[^a-z0-9._-]+", "-", stem.lower())
    stem = re.sub(r"[-_.]{2,}", "-", stem).strip("-_.")
    stem = (stem or "image")[:60].strip("-_.") or "image"
    candidate = f"{stem}.{ext}" if ext else stem
    number = 2
    while candidate in taken:
        candidate = f"{stem}-{number}.{ext}" if ext else f"{stem}-{number}"
        number += 1
    return candidate


def rewrite_references(index: Path, renamed: dict[str, str]) -> None:
    """يحدّث صورة المشاركة وصور النصّ التي تشير إلى اسم قديم بالضبط."""
    text = index.read_text(encoding="utf-8")
    front = FRONT.match(text)
    head, body = (text[:front.end()], text[front.end():]) if front else ("", text)

    def featured(match: "re.Match[str]") -> str:
        new = renamed.get(match.group(3).strip()) or renamed.get(unquote(match.group(3).strip()))
        return f"{match.group(1)}{match.group(2)}{new}{match.group(2)}" if new else match.group(0)

    def image(match: "re.Match[str]") -> str:
        target = match.group(1) or match.group(2)
        new = renamed.get(target) or renamed.get(unquote(target))
        if not new:
            return match.group(0)
        start = match.start(1) if match.group(1) is not None else match.start(2)
        end = match.end(1) if match.group(1) is not None else match.end(2)
        whole = match.group(0)
        return whole[:start - match.start()] + new + whole[end - match.start():]

    updated = FEATURED_LINE.sub(featured, head) + MARKDOWN_IMAGE.sub(image, body)
    if updated != text:
        index.write_text(updated, encoding="utf-8")


def normalise_file_names(bundle: Path) -> list[dict[str, str]]:
    """يعيد تسمية كل ملف بالحزمة اسمه غير مقبول. يعيد ما تغيّر (قبل/بعد)."""
    files = [item for item in sorted(bundle.iterdir())
             if item.is_file() and not item.name.startswith(("index.", "."))]
    taken = {item.name for item in files if SAFE_NAME.match(item.name)}
    renamed: dict[str, str] = {}
    for item in files:
        if SAFE_NAME.match(item.name):
            continue
        new_name = safe_name(item.name, taken)
        taken.add(new_name)
        item.rename(bundle / new_name)
        renamed[item.name] = new_name
    if renamed:
        for index in sorted(bundle.glob("index.*.md")):
            rewrite_references(index, renamed)
    return [{"before": old, "after": new} for old, new in renamed.items()]


def localise_lone_language_resources(bundle: Path) -> int:
    """يمنح موارد الحزمة أحاديّة اللغة لاحقةَ تلك اللغة، إن لم تكن الافتراضية.

    ‏Hugo ينسب المورد الذي لا يحمل لاحقة لغة إلى اللغة الافتراضية (العربية
    هنا). مقال إنجليزي وحده — بلا index.ar.md — تبقى صوره بلا صفحة تملكها:
    صورة النصّ تُسقط البناء، وصورة المشاركة تسقط بصمت إلى صورة الموقع. لم
    يحدث بعد في هذه المدونة (كل مقالاتها عربية أو ثنائية)، وحدث في مدونة
    zero2one.sa أول ما نُشر مقال بلغتها غير الافتراضية (2026-09-13).

    والحزمة ثنائية اللغة لا تُمسّ: صفحتها العربية تملك الموارد وتشاركها
    الإنجليزية، وإضافة لاحقة هناك تكسر المشاركة.
    """
    indexes = sorted(bundle.glob("index.*.md"))
    langs = {path.name.split(".")[1] for path in indexes}
    default_lang = json.loads(
        (ROOT / "controls" / "schema.json").read_text(encoding="utf-8")
    )["languages"]["default"]
    if default_lang in langs or len(langs) != 1:
        return 0

    lang = next(iter(langs))
    known = langs | {"en", "ar"}
    renamed: dict[str, str] = {}
    for item in sorted(bundle.iterdir()):
        if not item.is_file() or item.name.startswith("index."):
            continue
        stem, _, ext = item.name.rpartition(".")
        if not ext or stem.rpartition(".")[2] in known:
            continue
        new_name = f"{stem}.{lang}.{ext}"
        item.rename(bundle / new_name)
        renamed[item.name] = new_name

    if renamed:
        for index in indexes:
            text = index.read_text(encoding="utf-8")
            for old, new in renamed.items():
                text = text.replace(old, new)
            index.write_text(text, encoding="utf-8")
    return len(renamed)


def stage_bundle(bundle: Path, destination: Path) -> dict[str, object]:
    """ينسخ حزمة إلى مكانها المجهّز ويطبّق تحويلات التجهيز كلها.

    بنّاء المدونة يستدعيها أيضًا لنسخة سابقة من مقال منشور، فتمرّ النسخة
    السابقة بالتحويلات نفسها حرفيًّا.
    """
    shutil.copytree(bundle, destination)
    names = normalise_file_names(destination)
    renamed = localise_lone_language_resources(destination)
    notes = normalize_dates(destination) + demote_body_h1(destination)
    tables: list[dict[str, object]] = []
    for index in sorted(destination.glob("index.*.md")):
        for repair in repair_tables(index):
            tables.append({"file": index.name, **repair})
    return {"renamed": renamed, "names": names, "notes": notes, "tables": tables}


def prepare(
    source: Path,
    *,
    problems: dict[str, list[str]] | None = None,
    details: dict[str, dict[str, object]] | None = None,
) -> tuple[int, int]:
    """يجهّز content/ من المصدر.

    ``problems``: إن مُرّر، تُسجَّل فيه مشكلات المقال الواحد (BundleProblem)
    باسم مجلده ويُستبعد ذلك المقال وحده. بلا تمريره تُرفع كما كانت دائمًا.
    ``details``: يُملأ بما جرى لكل مقال (أرشفة، تواريخ، جداول، أسماء ملفات).
    مشكلات المحتوى كله (رابط رمزي، صفحات القسم) تُرفع في الحالتين.
    """
    reject_symlinks(source)
    source = source.resolve()
    if not source.is_dir():
        raise PrepareError(f"مجلد المحتوى غير موجود: {source}")
    if source == DESTINATION.resolve():
        raise PrepareError("المصدر لا يمكن أن يكون مجلد content المولّد نفسه")

    staging = ROOT / f".content-prepared-{uuid.uuid4().hex}"
    staging.mkdir()
    previous: Path | None = None
    copied = 0
    archived = 0
    try:
        index_files = sorted(source.glob("_index.*.md"))
        required_indexes = {"_index.en.md", "_index.ar.md"}
        present_indexes = {path.name for path in index_files}
        missing_indexes = required_indexes - present_indexes
        if missing_indexes:
            raise PrepareError(
                "صفحات قسم المدونة مفقودة: " + ", ".join(sorted(missing_indexes))
            )
        for index_file in index_files:
            shutil.copy2(index_file, staging / index_file.name)

        bundles = source / "blog"
        if bundles.is_dir():
            for bundle in sorted(p for p in bundles.iterdir() if p.is_dir() and not p.name.startswith(".")):
                try:
                    is_archived = bundle_is_archived(bundle)
                except BundleProblem as exc:
                    if problems is None:
                        raise BundleProblem(f"{bundle.name}: {exc}") from exc
                    problems.setdefault(bundle.name, []).append(str(exc))
                    continue
                if is_archived:
                    archived += 1
                    if details is not None:
                        details[bundle.name] = {"archived": True}
                    continue
                info = stage_bundle(bundle, staging / bundle.name)
                if details is not None:
                    details[bundle.name] = {"archived": False, **info}
                copied += 1

        (staging / MARKER).write_text(
            "هذا مجلد مولّد. لا تحرره؛ شغّل tools/prepare_content.py.\n",
            encoding="utf-8",
        )

        # لا نحذف مجلدًا لم تنشئه هذه الأداة. هذا يحمي checkout أو مجلدًا
        # محليًا وُضع باسم content/ بالخطأ من تنظيف واسع وصامت.
        if DESTINATION.exists() or DESTINATION.is_symlink():
            destination_marker = DESTINATION / MARKER
            if (
                DESTINATION.is_symlink()
                or destination_marker.is_symlink()
                or not destination_marker.is_file()
            ):
                raise PrepareError(
                    "مجلد content موجود لكنه ليس ناتج prepare_content؛ لن يُحذف آليًا"
                )
            previous = ROOT / f".content-previous-{uuid.uuid4().hex}"
            os.replace(DESTINATION, previous)
        try:
            os.replace(staging, DESTINATION)
        except OSError:
            if previous is not None and previous.exists() and not DESTINATION.exists():
                os.replace(previous, DESTINATION)
                previous = None
            raise
        if previous is not None:
            shutil.rmtree(previous)
            previous = None
    except OSError as exc:
        raise PrepareError(f"تعذّر نسخ المحتوى أو تثبيت المجلد المولّد: {exc}") from exc
    finally:
        if staging.exists():
            try:
                shutil.rmtree(staging)
            except OSError:
                # فشل التنظيف لا يخفي الخطأ الأصلي؛ المجلد عشوائي ومخفي ولا
                # يُستخدم في البناء ما لم يكتمل os.replace أعلاه.
                pass
        if previous is not None and previous.exists() and not DESTINATION.exists():
            try:
                os.replace(previous, DESTINATION)
            except OSError:
                pass
    return copied, archived


def describe(details: dict[str, dict[str, object]]) -> list[str]:
    """ما فعله التجهيز بكل مقال، سطرًا سطرًا للسجل."""
    lines: list[str] = []
    for name, info in sorted(details.items()):
        lines.extend(str(note) for note in info.get("notes", []) or [])
        for repair in info.get("tables", []) or []:
            if repair["columns"]:
                lines.append(f"{name}/{repair['file']}: أُضيف السطر الفاصل لجدول في السطر "
                             f"{repair['line']} ({repair['columns']} خانات)")
            else:
                lines.append(f"{name}/{repair['file']}: سطر عنوان الجدول في السطر "
                             f"{repair['line']} صار سطرًا عريضًا")
        for fixed in info.get("names", []) or []:
            lines.append(f"{name}: اسم الملف «{fixed['before']}» صار «{fixed['after']}»")
    return lines


def main() -> int:
    if len(sys.argv) != 2:
        print("  الاستخدام: prepare_content.py <content-source>")
        return 2
    details: dict[str, dict[str, object]] = {}
    try:
        copied, archived = prepare(Path(sys.argv[1]), details=details)
    except PrepareError as exc:
        print(f"  ❌ تجهيز المحتوى فشل: {exc}")
        return 1
    for note in describe(details):
        print(f"  ✏️  {note}")
    print(f"  ✅ جُهّزت {copied} حزمة · استُبعدت {archived} حزمة مؤرشفة")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
