#!/bin/bash
# Build the Linux app: one program, `rcx-tower`, packed with its udev rule into
#
#     dist/RCX-Tower-<version>-linux-<arch>.tar.gz
#
# Run on Linux:  ./build_linux.sh
# Needs Python 3.9+ with tkinter (Debian/Ubuntu: python3-tk python3-venv), and for NQC
# make, g++, flex and bison (Debian/Ubuntu: build-essential flex bison). Build on the
# oldest distribution you want to support: the program needs that glibc or newer.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VERSION="$("$PYTHON" -c 'import rcxtower; print(rcxtower.__version__)')"
ARCH="$(uname -m)"
PKG="RCX-Tower-$VERSION-linux-$ARCH"

echo "== Python packages"
"$PYTHON" -m pip install --quiet --upgrade pyinstaller pyusb libusb-package

# ---- NQC compiler (optional): without it the app still does firmware, remote control
# ---- and ready-made .rcx files, but cannot compile programs.
NQC_BIN=""
if [ -n "${NQC:-}" ] && [ -x "${NQC:-}" ]; then
    NQC_BIN="$NQC"                                  # NQC=/path/to/nqc ./build_linux.sh
elif [ "${SKIP_NQC:-}" != "1" ]; then
    echo "== Building NQC from source (set SKIP_NQC=1 to leave it out)"
    mkdir -p build
    if [ ! -d build/nqc-src ]; then
        git clone --depth 1 https://github.com/BrickBot/nqc.git build/nqc-src || true
    fi
    if [ -d build/nqc-src ]; then
        (cd build/nqc-src && make exec) > build/nqc-build.log 2>&1 || true
        for candidate in build/nqc-src/build/bin/nqc build/nqc-src/bin/nqc; do
            if [ -x "$candidate" ]; then
                NQC_BIN="$candidate"
                break
            fi
        done
    fi
fi
EXTRA=()
if [ -n "$NQC_BIN" ]; then
    echo "   NQC: $NQC_BIN"
    EXTRA+=(--add-binary "$NQC_BIN:.")
else
    echo "   NQC was NOT built (see build/nqc-build.log). The app will not be able to compile programs."
fi

echo "== Building the program"
rm -rf "dist/rcx-tower" "dist/$PKG" "dist/$PKG.tar.gz"
"$PYTHON" -m PyInstaller --noconfirm --clean --onefile --name rcx-tower \
    --add-data "rcxtower/data/firm0328.lgo:rcxtower/data" \
    --collect-all libusb_package \
    --hidden-import usb.backend.libusb1 \
    ${EXTRA[@]+"${EXTRA[@]}"} rcxtower_app.py

echo "== Checking the program starts and can load the USB library"
set +e
OUT="$(dist/rcx-tower status 2>&1)"
set -e
echo "$OUT" | sed 's/^/   /'
if echo "$OUT" | grep -q "cannot look"; then
    echo "The built program cannot load libusb." >&2
    exit 1
fi

echo "== Making dist/$PKG.tar.gz"
mkdir -p "dist/$PKG"
cp dist/rcx-tower "dist/$PKG/"
"$PYTHON" -c 'from rcxtower import tower_libusb as t; print(t.UDEV_RULE, end="")' > "dist/$PKG/60-lego-usb-tower.rules"
cat > "dist/$PKG/README.txt" <<EOF
RCX Tower $VERSION for Linux ($ARCH)

Start it:   ./rcx-tower          (the window)
            ./rcx-tower --help   (the commands: status, firmware, download, ...)

The tower needs permission once: click "Allow USB access" on the Setup tab, or run
    sudo ./rcx-tower install-driver
or copy 60-lego-usb-tower.rules to /etc/udev/rules.d/ and replug the tower.

NQC (the compiler) and the LEGO firmware 3.2.8 are included.
EOF
tar -C dist -czf "dist/$PKG.tar.gz" "$PKG"
echo "Done: dist/$PKG.tar.gz"
