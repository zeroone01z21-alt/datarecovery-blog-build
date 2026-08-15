#!/usr/bin/env python3
"""
مدقّق الروابط الداخلية الخارجة من المدونة
==========================================

يفحص كل رابط في مقالات المدونة يشير إلى **الموقع** لا إلى المدونة، ويتأكد
أن الصفحة المقصودة موجودة فعلًا.

لماذا هذا الفاحص موجود
----------------------
لوحة الكاتب تتيح إدراج روابط داخل النص، والغرض التجاري من المدونة هو تحديدًا
أن يحيل المقال إلى صفحة الخدمة المناسبة. لكن `check_seo.py` يفحص الروابط
**داخل** `/blog/` فقط، فرابط إلى `/services/hdd.html` يخرج من نطاقه.

النتيجة بلا هذا الفاحص: خطأ مطبعي واحد — `/services/phone.html` بدل
`phones` — يُنشر بصمت ويعطي الزائر 404 في اللحظة التي كان فيها أقرب ما يكون
إلى طلب الخدمة. وهذه أغلى 404 ممكنة على الموقع.

ولماذا الروابط النسبية إلزامية
-------------------------------
رابط مطلق مثل `https://datarecovery-sa.com/services/hdd.html` يعمل في
الإنتاج ويكسر في المعاينة، لأن المعاينة على نطاق فرعي مختلف. العطل صامت:
الصفحة تظهر سليمة والرابط يقود إلى الإنتاج بدل النسخة قيد المراجعة.

الاستخدام:
    python3 tools/check_internal_links.py <مجلد-مخرجات-المدونة> <جذر-مستودع-الموقع>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

SITE_HOST = "datarecovery-sa.com"
# روابط تخصّ المدونة نفسها يفحصها check_seo.py، فلا تُكرَّر هنا.
BLOG_PREFIX = "/blog/"
HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
# نفحص متن المقال فقط. الهيكل (الهيدر والفوتر) يأتي من مولّد الموقع ويُفحص هناك.
BODY = re.compile(r"<main\b[^>]*>(.*?)</main>", re.I | re.S)


def article_pages(public: Path) -> list[Path]:
    return sorted(p for p in public.rglob("*.html") if p.name != "404.html")


def site_has(site: Path, path: str) -> bool:
    """هل يقابل المسار ملفًا فعليًا في مستودع الموقع؟"""
    clean = unquote(path.split("#")[0].split("?")[0]).lstrip("/")
    if not clean or clean.endswith("/"):
        clean = (clean + "index.html") if clean else "index.html"
    target = site / clean
    if target.is_file():
        return True
    # الموقع يقبل الطلبات بلا امتداد أيضًا (قاعدة في .htaccess)
    return (site / f"{clean}.html").is_file()


def main() -> int:
    if len(sys.argv) != 3:
        print("  الاستخدام: check_internal_links.py <مخرجات المدونة> <جذر الموقع>")
        return 2

    public, site = Path(sys.argv[1]), Path(sys.argv[2])
    for label, path in (("مخرجات المدونة", public), ("جذر الموقع", site)):
        if not path.is_dir():
            print(f"  ❌ {label} غير موجود: {path}")
            return 2

    problems: list[tuple[str, str]] = []
    pages = article_pages(public)
    checked = 0

    for page in pages:
        html = page.read_text(encoding="utf-8", errors="replace")
        body = "\n".join(BODY.findall(html)) or html
        rel = str(page.relative_to(public))

        for href in HREF.findall(body):
            href = href.strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "data:")):
                continue

            parts = urlsplit(href)

            # رابط مطلق إلى نطاقنا: يعمل في الإنتاج ويكسر في المعاينة.
            if parts.netloc:
                if parts.netloc.replace("www.", "") == SITE_HOST:
                    problems.append((rel, (
                        f"رابط داخلي مكتوب بالكامل: «{href}» — اكتبه نسبيًّا "
                        f"«{parts.path or '/'}» وإلا كسر في المعاينة."
                    )))
                continue  # نطاق خارجي: ليس شأننا

            if not href.startswith("/"):
                continue  # نسبي داخل المدونة — يفحصه check_seo
            if href.startswith(BLOG_PREFIX):
                continue  # داخل المدونة — يفحصه check_seo

            checked += 1
            if not site_has(site, parts.path):
                problems.append((rel, (
                    f"الرابط «{href}» لا يقابل أي صفحة في الموقع. "
                    f"تأكد من المسار، أو اختر صفحة الخدمة الصحيحة."
                )))

    if not problems:
        print(f"  ✅ الروابط الداخلية سليمة — {checked} رابطًا إلى الموقع من {len(pages)} صفحة")
        return 0

    print(f"  ❌ {len(problems)} مشكلة في الروابط الداخلية\n")
    last = None
    for f, m in problems:
        if f != last:
            print(f"  ── {f}")
            last = f
        print(f"     • {m}")
    print("\n  البناء متوقّف حتى تُصلَح هذه الروابط.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
