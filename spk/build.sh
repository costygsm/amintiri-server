#!/bin/sh
# Face pachetul DSM 7.2 (.spk) pentru Package Center → Instalare manuală, cu Python-ul lui în el:
#   sh spk/build.sh x86_64     (Intel/AMD: DS224+, DS923+, …)
#   sh spk/build.sh armv8      (ARM pe 64 de biți: DS223j, DS220j, DS120j, …)
# Rezultatul: spk/dist/amintiri-<versiune>-<arch>.spk. Cere curl și uv.
set -eu
ARCH=${1:?folosire: $0 x86_64|armv8}
PY_REL=20261003
case "$ARCH" in
  x86_64) PY=x86_64;  SHA=731af898886c5f821890dc901eca3c651cca8e51fa7308c159d12a1194aeac91 ;;
  armv8)  PY=aarch64; SHA=6541297dd1798dec8b98c3ad7492808a5b9d1c126801ceb2011e7754cd20d1ce ;;
  *) echo "procesor necunoscut: $ARCH" >&2; exit 2 ;;
esac
HERE=$(cd "$(dirname "$0")" && pwd)
SRV=$(dirname "$HERE")
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRV/poze/__init__.py")

# Python de sine stătător (python-build-standalone): DSM are doar 3.8, serverul cere 3.10+
TGZ=cpython-3.12.15+$PY_REL-$PY-unknown-linux-gnu-install_only_stripped.tar.gz
mkdir -p "$HERE/.cache" "$HERE/dist"
[ -f "$HERE/.cache/$TGZ" ] || curl -fsSL -o "$HERE/.cache/$TGZ" \
  "https://github.com/astral-sh/python-build-standalone/releases/download/$PY_REL/$TGZ"
echo "$SHA  $HERE/.cache/$TGZ" | sha256sum -c --quiet -

W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
mkdir -p "$W/target" "$W/pkg"
tar -xzf "$HERE/.cache/$TGZ" -C "$W/target"
LIB=$W/target/python/lib/python3.12
rm -rf "$LIB/test" "$LIB/idlelib" "$LIB/tkinter" "$LIB/turtledemo" "$LIB/ensurepip" "$LIB/lib-dynload/_tkinter"* \
  "$W/target/python/lib/"tcl* "$W/target/python/lib/"tk* "$W/target/python/lib/"thread* "$W/target/python/lib/"itcl* \
  "$W/target/python/lib/"libtcl* "$W/target/python/lib/"libtk*

# dependențele din pyproject.toml, ca roți gata compilate pentru procesorul NAS-ului (glibc 2.36 pe DSM 7.2);
# tzdata: fusurile orare nu depind de ce are DSM-ul
DEPS=$(python3 -c 'import sys,tomllib;print("\n".join(tomllib.load(open(sys.argv[1],"rb"))["project"]["dependencies"]))' "$SRV/pyproject.toml")
echo "$DEPS" > "$W/req.txt"
echo "tzdata" >> "$W/req.txt"
uv pip install --quiet --target "$LIB/site-packages" --python-platform "$PY-manylinux_2_28" \
  --python-version 3.12 --only-binary :all: -r "$W/req.txt"
tar -C "$SRV" -cf - --exclude=__pycache__ poze | tar -C "$W/target" -xf -

# licențele componentelor incluse: textele stau lângă fiecare roată (*.dist-info/licenses), aici e cuprinsul
{
  echo "Amintiri bundles third-party software. Licence texts are in python/lib/python3.12/site-packages/*.dist-info/"
  echo "(licenses/ and, for PyAV, sboms/ listing the bundled FFmpeg libraries) and in python/ (Python itself)."
  echo
  echo "- Python (python-build-standalone): PSF License and the licences of its bundled libraries"
  echo "- PyAV: BSD-3-Clause. Its wheel bundles the FFmpeg libraries (LGPL-3.0-or-later; sources: https://ffmpeg.org)"
  echo "  together with codec libraries including x264 and x265 (GPL-2.0-or-later), dav1d, libvpx, SVT-AV1 and others;"
  echo "  build scripts and sources: https://github.com/PyAV-Org/pyav-ffmpeg"
  echo "- Pillow (MIT-CMU), pillow-heif with libheif/libde265 (LGPL-3.0), FastAPI, Starlette, Pydantic, Uvicorn, httpx"
  echo
  for d in "$LIB/site-packages/"*.dist-info; do
    n=$(sed -n 's/^Name: //p' "$d/METADATA"); v=$(sed -n 's/^Version: //p' "$d/METADATA")
    l=$(sed -n 's/^License-Expression: //p; s/^License: //p' "$d/METADATA" | head -1)
    echo "$n $v${l:+ — $l}"
  done
} > "$W/target/THIRD_PARTY_LICENSES.txt"

# iconițele meniului DSM; ui/config îl scrie postinst, cu adresa web din asistent
mkdir -p "$W/target/ui"
cp -R "$HERE/ui/images" "$W/target/ui/"
tar -czf "$W/pkg/package.tgz" -C "$W/target" .
sed -e "s/@VERSION@/$VER-${SPK_BUILD:-1}/" -e "s/@ARCH@/$ARCH/" -e "s/@SIZE@/$(du -sk "$W/target" | cut -f1)/" \
  "$HERE/INFO.in" > "$W/pkg/INFO"
cp -R "$HERE/conf" "$HERE/scripts" "$HERE/WIZARD_UIFILES" "$HERE/PACKAGE_ICON.PNG" "$HERE/PACKAGE_ICON_256.PNG" "$W/pkg/"
chmod 755 "$W/pkg/scripts/"*
OUT=$HERE/dist/amintiri-$VER-$ARCH.spk
tar -cf "$OUT" -C "$W/pkg" INFO package.tgz conf scripts WIZARD_UIFILES PACKAGE_ICON.PNG PACKAGE_ICON_256.PNG
echo "$OUT ($(du -h "$OUT" | cut -f1))"
