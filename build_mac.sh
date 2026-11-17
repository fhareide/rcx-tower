#!/bin/bash
# Build "dist/RCX Tower.app" and a .dmg for macOS. Run on a Mac:
#
#     ./build_mac.sh
#
# Needs Python 3.9+ with tkinter (the python.org installer has it) and the Xcode
# command line tools (xcode-select --install). Everything else is installed here.
# The result is for the processor of the Mac it is built on (Apple silicon or Intel).
#
# The app is not signed with an Apple developer certificate, so the first time it
# is opened macOS refuses: right-click the app, choose Open, then Open again.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
NAME="RCX Tower"
VERSION="$("$PYTHON" -c 'import rcxtower; print(rcxtower.__version__)')"
ARCH="$(uname -m)"
DMG="dist/RCX-Tower-$VERSION-mac-$ARCH.dmg"

echo "== Python packages"
"$PYTHON" -m pip install --quiet --upgrade pyinstaller pyusb libusb-package

# ---- NQC compiler (optional): without it the app still does firmware, remote control
# ---- and ready-made .rcx files, but cannot compile programs.
NQC_BIN=""
if [ -n "${NQC:-}" ] && [ -x "${NQC:-}" ]; then
    NQC_BIN="$NQC"                                  # NQC=/path/to/nqc ./build_mac.sh
elif [ "${SKIP_NQC:-}" != "1" ]; then
    echo "== Building NQC from source (set SKIP_NQC=1 to leave it out)"
    mkdir -p build
    if [ ! -d build/nqc-src ]; then
        git clone --depth 1 https://github.com/BrickBot/nqc.git build/nqc-src || true
    fi
    if [ -d build/nqc-src ]; then
        (cd build/nqc-src && make) > build/nqc-build.log 2>&1 || true
        if [ -x build/nqc-src/bin/nqc ]; then
            NQC_BIN="build/nqc-src/bin/nqc"
        fi
    fi
fi
EXTRA=()
if [ -n "$NQC_BIN" ]; then
    echo "   NQC: $NQC_BIN"
    EXTRA+=(--add-binary "$NQC_BIN:.")
else
    echo "   NQC was NOT built (see build/nqc-build.log). The app will not be able to compile programs."
fi

# ---- icon (optional): turn the Windows icon into a Mac one
ICON=()
if sips -s format icns rcxtower/data/rcxtower.ico --out build/rcxtower.icns > /dev/null 2>&1; then
    ICON=(--icon build/rcxtower.icns)
fi

echo "== Building the app"
rm -rf "dist/$NAME.app" "dist/$NAME"
"$PYTHON" -m PyInstaller --noconfirm --clean --windowed --name "$NAME" \
    --osx-bundle-identifier "io.github.fhareide.rcxtower" \
    --add-data "rcxtower/data/firm0328.lgo:rcxtower/data" \
    --collect-all libusb_package \
    --hidden-import usb.backend.libusb1 \
    ${ICON[@]+"${ICON[@]}"} ${EXTRA[@]+"${EXTRA[@]}"} rcxtower_app.py

# An ad-hoc signature: Apple silicon Macs refuse to run code with none at all.
codesign --force --deep --sign - "dist/$NAME.app"

echo "== Checking the app starts and can load the USB library"
set +e
OUT="$("dist/$NAME.app/Contents/MacOS/$NAME" status 2>&1)"
set -e
echo "$OUT" | sed 's/^/   /'
if echo "$OUT" | grep -q "cannot look"; then
    echo "The built app cannot load libusb." >&2
    exit 1
fi

echo "== Making $DMG"
STAGE="$(mktemp -d)"
cp -R "dist/$NAME.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" > /dev/null
rm -rf "$STAGE"
echo "Done: $DMG"
