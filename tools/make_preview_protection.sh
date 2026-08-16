#!/bin/bash
# =============================================================================
# توليد ملفَّي حماية لوحة المعاينة
#
# ينتج .htpasswd و .htaccess جاهزين للرفع إلى مجلد المعاينة على الاستضافة.
#
# لماذا لا تُستخدم أداة hPanel «Password Protect Directories»:
#   أسقطت خادم الويب بالكامل في المشروع الشقيق (2026-08-03). الأعراض: قطع
#   TLS من الخارج بينما FTP و hPanel يعملان. عاد فورًا عند إزالة الحماية.
#   ملفان يدويان يفعلان الشيء نفسه بلا هذا الخطر.
#
# ولماذا الحماية شرط لا تحسين:
#   سير عمل المعاينة (preview.yml) **يسحب** .htaccess القائم من الخادم ويتحقق
#   أن Basic Auth ما زال فيه قبل أن يرفع اللوحة. بلا الملفين يفشل أول رفع.
#
# Run: bash tools/make_preview_protection.sh
# =============================================================================
set -euo pipefail

OUT="${1:-$HOME/Downloads/preview-protection}"
USER_NAME="writer"
REMOTE_DIR="/home/u497805864/domains/datarecovery-sa.com/public_html/preview"

command -v htpasswd >/dev/null 2>&1 || { echo "❌ htpasswd غير متاح."; exit 1; }

echo "توليد حماية لوحة المعاينة"
echo "  المستخدم: $USER_NAME"
echo
printf "اكتب كلمة المرور التي تريدها (لن تظهر): "
read -rs PASS1; echo
printf "أعدها للتأكيد: "
read -rs PASS2; echo

[ "$PASS1" = "$PASS2" ] || { echo "❌ الكلمتان غير متطابقتين."; exit 1; }
[ ${#PASS1} -ge 12 ] || { echo "❌ استخدم 12 محرفًا على الأقل — هذه بيانات دخول تُترك سنوات."; exit 1; }

mkdir -p "$OUT"

# ‏-B = bcrypt، و-n يطبع بدل الكتابة، فلا تمرّ الكلمة في argv لأي أمر آخر.
htpasswd -nbB "$USER_NAME" "$PASS1" > "$OUT/.htpasswd"
unset PASS1 PASS2

# الأسطر الثلاثة التي يتحقق منها sanitize_preview_htaccess.py حرفيًّا.
# ولا تعليمة Header إطلاقًا — يرفضها الفاحص لأنها قد تُسقط الخادم.
cat > "$OUT/.htaccess" <<EOF
# حماية لوحة الكاتب ومعاينة المسودات.
# يقرأ سير عمل المعاينة هذا الملف قبل كل رفع ويتحقق من بقاء الأسطر الثلاثة.
AuthType Basic
AuthName "Preview"
AuthUserFile $REMOTE_DIR/.htpasswd
Require valid-user
EOF

chmod 644 "$OUT/.htpasswd" "$OUT/.htaccess"

echo
echo "✅ جاهزان في: $OUT"
echo
echo "الخطوة التالية — ارفعهما إلى مجلد المعاينة:"
echo "  hPanel ← Files ← File Manager"
echo "  $REMOTE_DIR"
echo "  فعّل «إظهار الملفات المخفية»، ثم اسحب الملفين وأفلتهما."
echo
echo "ثم افتح https://preview.datarecovery-sa.com/ — يجب أن يطلب اسم مستخدم وكلمة مرور."
echo
echo "⚠️  احفظ كلمة المرور في مدير كلمات المرور الآن. لا تُسترجع من الملف — مشفّرة."
