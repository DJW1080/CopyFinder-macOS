#!/usr/bin/env bash
set -euo pipefail

APPLICATION_NAME="CopyFinder"
APPLICATION_VERSION="0.1.0-beta.1"
TARGET_ARCHITECTURE="x86_64"
DEPLOYMENT_TARGET="10.15"
MAX_BUILD_SECONDS=110

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
BUILD_ROOT="${PROJECT_ROOT}/build/macos"
DIST_ROOT="${PROJECT_ROOT}/dist/macos"
APPLICATION_BUNDLE="${BUILD_ROOT}/${APPLICATION_NAME}.app"
CONTENTS_DIRECTORY="${APPLICATION_BUNDLE}/Contents"
EXECUTABLE_DIRECTORY="${CONTENTS_DIRECTORY}/MacOS"
RESOURCES_DIRECTORY="${CONTENTS_DIRECTORY}/Resources"
EXECUTABLE_PATH="${EXECUTABLE_DIRECTORY}/${APPLICATION_NAME}"
ARCHIVE_BASENAME="${APPLICATION_NAME}-macOS-${APPLICATION_VERSION}-${TARGET_ARCHITECTURE}"
START_SECONDS=${SECONDS}

rm -rf "${BUILD_ROOT}" "${DIST_ROOT}"
mkdir -p "${EXECUTABLE_DIRECTORY}" "${RESOURCES_DIRECTORY}" "${DIST_ROOT}"

SDK_PATH="$(xcrun --sdk macosx --show-sdk-path)"
SOURCE_FILES=("${PROJECT_ROOT}"/Sources/*.swift)

xcrun swiftc \
  -target "${TARGET_ARCHITECTURE}-apple-macosx${DEPLOYMENT_TARGET}" \
  -sdk "${SDK_PATH}" \
  -O \
  -whole-module-optimization \
  -framework AppKit \
  -framework Combine \
  -framework CryptoKit \
  -framework SwiftUI \
  "${SOURCE_FILES[@]}" \
  -o "${EXECUTABLE_PATH}"

cp "${PROJECT_ROOT}/packaging/macos/Info.plist" "${CONTENTS_DIRECTORY}/Info.plist"
cp "${PROJECT_ROOT}/Resources/"*.png "${RESOURCES_DIRECTORY}/"
chmod 755 "${EXECUTABLE_PATH}"
codesign --force --deep --sign - "${APPLICATION_BUNDLE}"

"${EXECUTABLE_PATH}" --smoke-test > "${DIST_ROOT}/smoke-test.json"

ditto -c -k --sequesterRsrc --keepParent \
  "${APPLICATION_BUNDLE}" \
  "${DIST_ROOT}/${ARCHIVE_BASENAME}.zip"
hdiutil create \
  -volname "${APPLICATION_NAME}" \
  -srcfolder "${APPLICATION_BUNDLE}" \
  -ov \
  -format UDZO \
  "${DIST_ROOT}/${ARCHIVE_BASENAME}.dmg" >/dev/null

(
  cd "${DIST_ROOT}"
  shasum -a 256 "${ARCHIVE_BASENAME}.dmg" "${ARCHIVE_BASENAME}.zip" > SHA256SUMS
)

ELAPSED_SECONDS=$((SECONDS - START_SECONDS))
COMMIT_SHA="$(git -C "${PROJECT_ROOT}" rev-parse HEAD)"
cat > "${DIST_ROOT}/distribution.json" <<EOF
{
  "application": "${APPLICATION_NAME}",
  "version": "${APPLICATION_VERSION}",
  "architecture": "${TARGET_ARCHITECTURE}",
  "minimum_macos": "${DEPLOYMENT_TARGET}",
  "commit": "${COMMIT_SHA}",
  "elapsed_seconds": ${ELAPSED_SECONDS},
  "signature": "ad-hoc; no Developer ID or notarization",
  "test": "one duplicate-detection smoke test"
}
EOF

if (( ELAPSED_SECONDS > MAX_BUILD_SECONDS )); then
  echo "Build exceeded ${MAX_BUILD_SECONDS} seconds (${ELAPSED_SECONDS}s)." >&2
  exit 1
fi

echo "Built and packaged ${ARCHIVE_BASENAME} in ${ELAPSED_SECONDS} seconds."
