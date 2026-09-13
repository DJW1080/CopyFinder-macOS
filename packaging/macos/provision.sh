#!/bin/bash
# Run only on an ephemeral Intel Mac builder: dependencies compile from source.
set -euo pipefail
MACPORTS_VERSION=2.12.6
MACPORTS_SHA256=d4d77de931a0442d0d144e1b3033b6285d51091b9d9e6f73c4e02e3627be29a6
MACPORTS_PREFIX=/opt/local
DEPLOYMENT_TARGET=10.15
BUILD_ARCH=x86_64
BUILD_JOBS=3
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != "$BUILD_ARCH" ]]; then
    echo 'Provisioning requires an Intel macOS builder.' >&2
    exit 1
fi
if [[ -e "$MACPORTS_PREFIX/etc/macports/macports.conf" ]]; then
    echo 'Refusing to modify an existing MacPorts installation; use a fresh builder.' >&2
    exit 1
fi
BUILD_DIRECTORY=$(mktemp -d)
cd "$BUILD_DIRECTORY"
ARCHIVE="MacPorts-${MACPORTS_VERSION}.tar.bz2"
curl --fail --location --output "$ARCHIVE" "https://github.com/macports/macports-base/releases/download/v${MACPORTS_VERSION}/${ARCHIVE}"
printf '%s  %s\n' "$MACPORTS_SHA256" "$ARCHIVE" | shasum -a 256 -c -
tar -xjf "$ARCHIVE"
cd "MacPorts-${MACPORTS_VERSION}"
./configure --prefix="$MACPORTS_PREFIX"
make -j "$BUILD_JOBS"
sudo make install
# Settings apply to the whole graph; -s prevents newer host binary archives.
sudo tee -a "$MACPORTS_PREFIX/etc/macports/macports.conf" >/dev/null <<CONFIG
macosx_deployment_target $DEPLOYMENT_TARGET
build_arch $BUILD_ARCH
buildfromsource always
buildmakejobs $BUILD_JOBS
CONFIG
sudo tee -a "$MACPORTS_PREFIX/etc/macports/variants.conf" >/dev/null <<'VARIANTS'
+quartz -x11
VARIANTS
sudo "$MACPORTS_PREFIX/bin/port" -v sync
sudo "$MACPORTS_PREFIX/bin/port" -v -s install gtk4 +quartz -x11
sudo "$MACPORTS_PREFIX/bin/port" -v -s install python313 py313-gobject3 py313-Pillow py313-pyobjc py313-pyinstaller
"$MACPORTS_PREFIX/bin/port" installed
