#!/usr/bin/env python3
"""
مدقّق الروابط في نصّ المقالات
==============================

يفحص كل رابط في **نصّ** المقال (داخل ‎.post-body‎) يشير إلى الموقع أو إلى
المدونة، ويتأكد أن الصفحة المقصودة موجودة فعلًا.

لماذا هذا الفاحص موجود
----------------------
لوحة الكاتب تتيح إدراج روابط داخل النص، والغرض التجاري من المدونة هو تحديدًا
أن يحيل المقال إلى صفحة الخدمة المناسبة. خطأ مطبعي واحد — `/services/phone.html`
بدل `phones` — يُنشر بصمت ويعطي الزائر 404 في اللحظة التي كان فيها أقرب ما يكون
إلى طلب الخدمة. وهذه أغلى 404 ممكنة على الموقع. و`check_seo.py` لا يفحص روابط
`<a>` إطلاقًا (عناصر `<link>` وحدها)، فلا شيء غير هذا الفاحص يمسكها.

ما يحجز وما يقترح (2026-11-15، بقرار المالك)
--------------------------------------------
- رابط إلى صفحة في الموقع غير موجودة ← **يحجز مقاله وحده** (tools/build_blog.py).
- رابط إلى مقال أو صفحة في المدونة غير موجودة ← **اقتراح**. لا حجز هنا عمدًا:
  مقال يربط بمقال آخر محجوز اليوم كان سيُحجز معه، ثم كل من يربط به — سلسلة
  تُخرج من الموقع مقالات سليمة بسبب مقال واحد.
- رابط مكتوب كاملًا (https://datarecovery-sa.com/...) ووجهته سليمة ← **اقتراح**
  واحد لكل صفحة: يعمل في الإنتاج، لكنه في المعاينة يقود إلى الإنتاج بدل النسخة
  قيد المراجعة.

لماذا HTMLParser لا نمط نصّي
----------------------------
حتى 2026-11-15 كان النمط `href=["']…["']`، وHugo بـ--minify يحذف التنصيص حين
يجوز (`href=https://…`)، فلم تجد البوابة رابطًا تفحصه منذ أُنشئت («0 رابطًا»).
والنطاق كان ‎<main>‎ كله، وهو عند هذا الموقع يضمّ الهيدر والفوتر أيضًا. المحلّل
يقرأ القيم بتنصيص وبدونه، والفحص صار مقصورًا على ‎.post-body‎: نصّ الكاتب وحده.

الاستخدام:
    python3 tools/check_internal_links.py <مخرجات-المدونة> <جذر-مستودع-الموقع> \\
        [--json-out <ملف>] [--warnings-out <ملف>]
"""

from __future__ import annotations

import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

SITE_HOST = "datarecovery-sa.com"
BLOG_PREFIX = "/blog/"
SKIP_SCHEMES = ("mailto:", "tel:", "data:", "javascript:", "sms:")


class BodyLinks(HTMLParser):
    """قيم href لروابط <a> داخل ‎<div class="post-body">‎ وما تحته وحده."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if self.depth:
            if tag == "div":
                self.depth += 1          # غلاف الجدول وما شابه داخل النص
            elif tag == "a" and values.get("href", "").strip():
                self.links.append(values["href"].strip())
        elif tag == "div" and "post-body" in values.get("class", "").split():
            self.depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self.depth and tag == "div":
            self.depth -= 1


def body_links(html: str) -> list[str]:
    parser = BodyLinks()
    parser.feed(html)
    parser.close()
    return parser.links


def resolves(root: Path, path: str) -> bool:
    """هل يقابل المسار ملفًا فعليًا تحت root؟ (‎/x/‎ ← x/index.html، و‎/x‎ ← x.html)"""
    clean = unquote(path.split("#")[0].split("?")[0]).lstrip("/")
    if ".." in clean.split("/"):
        return False
    if not clean or clean.endswith("/"):
        clean = (clean + "index.html") if clean else "index.html"
    if (root / clean).is_file():
        return True
    # الموقع يقبل الطلبات بلا امتداد، وبلا شرطة مائلة أخيرة لمجلد فيه index.html
    return (root / f"{clean}.html").is_file() or (root / clean / "index.html").is_file()


def classify(href: str) -> tuple[str, str, bool] | None:
    """(النوع site|blog، المسار، مكتوب كاملًا؟) — أو None لرابط خارجي أو غير مفحوص."""
    if not href or href.startswith("#") or href.lower().startswith(SKIP_SCHEMES):
        return None
    parts = urlsplit(href)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.netloc:
        if host != SITE_HOST or parts.scheme not in ("http", "https", ""):
            return None                    # نطاق خارجي: ليس شأننا
        path, absolute = parts.path or "/", True
    elif href.startswith("/"):
        path, absolute = parts.path or "/", False
    else:
        return None                        # نسبي إلى الصفحة نفسها: نادر، ولا يُخمَّن
    kind = "blog" if (path + "/").startswith(BLOG_PREFIX) else "site"
    return kind, path, absolute


def check(public: Path, site: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str]], int]:
    """(مشكلات تحجز، اقتراحات، عدد الروابط المفحوصة)."""
    problems: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []
    checked = 0
    for page in sorted(public.rglob("*.html")):
        if page.name == "404.html":
            continue
        rel = page.relative_to(public).as_posix()
        full: list[str] = []
        for href in body_links(page.read_text(encoding="utf-8", errors="replace")):
            found = classify(href)
            if found is None:
                continue
            kind, path, absolute = found
            checked += 1
            if absolute:
                full.append(href)
            if kind == "site":
                if not resolves(site, path):
                    problems.append((rel, f"الرابط «{href}» لا يقابل أي صفحة في الموقع. "
                                          "صحّحه أو احذفه، ثم احفظ."))
            else:
                inner = path[len(BLOG_PREFIX):] if path.startswith(BLOG_PREFIX) else ""
                if not resolves(public, "/" + inner):
                    warnings.append((rel, f"الرابط «{href}» يشير إلى صفحة في المدونة غير موجودة "
                                          "أو غير منشورة بعد. تأكّد من الرابط، أو انتظر نشر المقال."))
        if full:
            warnings.append((rel, f"روابط داخلية مكتوبة كاملًا (عددها {len(full)})، مثل «{full[0]}». "
                                  "يُستحسن كتابتها من / مثل «/contact.html» كي تعمل في المعاينة أيضًا."))
    return problems, warnings, checked


def write_json(path: Path | None, items: list[tuple[str, str]]) -> None:
    if path is not None:
        path.write_text(json.dumps([{"page": page, "message": message} for page, message in items],
                                   ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = sys.argv[1:]
    outputs: dict[str, Path | None] = {"--json-out": None, "--warnings-out": None}
    for flag in outputs:
        if flag in args:
            at = args.index(flag)
            if at + 1 >= len(args):
                print(f"  {flag} يحتاج مسار ملف")
                return 2
            outputs[flag] = Path(args[at + 1])
            del args[at:at + 2]
    if len(args) != 2:
        print("  الاستخدام: check_internal_links.py <مخرجات المدونة> <جذر الموقع> "
              "[--json-out <ملف>] [--warnings-out <ملف>]")
        return 2

    public, site = Path(args[0]), Path(args[1])
    for label, path in (("مخرجات المدونة", public), ("جذر الموقع", site)):
        if not path.is_dir():
            print(f"  ❌ {label} غير موجود: {path}")
            return 2

    problems, warnings, checked = check(public, site)
    # --json-out / --warnings-out: منظّمةً بمسار الصفحة، كي ينسب بنّاء المدونة
    # رابطًا مكسورًا إلى مقاله فيحجزه وحده، والاقتراح إلى مقاله فيعرضه للكاتب.
    write_json(outputs["--json-out"], problems)
    write_json(outputs["--warnings-out"], warnings)

    if warnings:
        print(f"  💡 {len(warnings)} اقتراح لا يحجز مقالًا:")
        for page, message in warnings:
            print(f"     • {page}: {message}")
    if not problems:
        print(f"  ✅ الروابط في نصوص المقالات سليمة — الروابط الداخلية المفحوصة: {checked}")
        return 0

    print(f"  ❌ {len(problems)} رابط مكسور إلى الموقع\n")
    last = None
    for page, message in problems:
        if page != last:
            print(f"  ── {page}")
            last = page
        print(f"     • {message}")
    print("\n  المقال صاحب الرابط يُحجز حتى يُصحَّح.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
