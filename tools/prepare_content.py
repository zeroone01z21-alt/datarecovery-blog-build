#!/usr/bin/env python3
"""جهّز محتوى Hugo من مستودع التحرير واستبعد الحزم المؤرشفة بالكامل.

الاستخدام:
    python3 tools/prepare_content.py <content-source>

الوجهة ثابتة عمدًا: ``content/`` داخل مستودع البناء. هذا يمنع تمرير مسار
خاطئ إلى عملية تنظيف ويجعل الناتج مؤقتًا قابلًا لإعادة التوليد.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import uuid
from pathlib import Path

from check_content import parse_front_matter


ROOT = Path(__file__).resolve().parent.parent
DESTINATION = ROOT / "content"
MARKER = ".generated-by-prepare-content"


class PrepareError(RuntimeError):
    pass


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
    except OSError as exc:
        raise PrepareError(f"تعذّرت قراءة {path}") from exc
    if data is None:
        raise PrepareError(f"ملف بلا front matter: {path}")
    return data


def bundle_is_archived(bundle: Path) -> bool:
    indexes = sorted(bundle.glob("index.*.md"))
    if not indexes:
        raise PrepareError(f"حزمة بلا index.<lang>.md: {bundle}")
    states = {bool(front_matter(path).get("archived", False)) for path in indexes}
    if len(states) != 1:
        raise PrepareError(f"حالة archived مختلفة بين ترجمات الحزمة: {bundle.name}")
    return states == {True}


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


def prepare(source: Path) -> tuple[int, int, list[str]]:
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
    notes: list[str] = []
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
                if bundle_is_archived(bundle):
                    archived += 1
                    continue
                shutil.copytree(bundle, staging / bundle.name)
                notes.extend(demote_body_h1(staging / bundle.name))
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
    return copied, archived, notes


def main() -> int:
    if len(sys.argv) != 2:
        print("  الاستخدام: prepare_content.py <content-source>")
        return 2
    try:
        copied, archived, notes = prepare(Path(sys.argv[1]))
    except PrepareError as exc:
        print(f"  ❌ تجهيز المحتوى فشل: {exc}")
        return 1
    for note in notes:
        print(f"  ✏️  {note}")
    print(f"  ✅ جُهّزت {copied} حزمة · استُبعدت {archived} حزمة مؤرشفة")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
