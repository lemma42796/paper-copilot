#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
BUILD_ROOT="$REPO_ROOT/build/macos-distribution"
FINAL_APP="$REPO_ROOT/dist/macos/PaperCopilot.app"
HELPER_NAME="PaperCopilotRuntime"
HELPER_DIST="$BUILD_ROOT/helper/$HELPER_NAME"
DERIVED_DATA="$BUILD_ROOT/DerivedData"
BUILT_APP="$DERIVED_DATA/Build/Products/Release/PaperCopilot.app"
SIGN_IDENTITY="${PAPER_COPILOT_SIGN_IDENTITY:--}"

rm -rf "$BUILD_ROOT" "$FINAL_APP"
mkdir -p "$BUILD_ROOT/spec" "$(dirname -- "$FINAL_APP")"

cd "$REPO_ROOT"
uv run pyinstaller \
    --noconfirm \
    --clean \
    --onedir \
    --name "$HELPER_NAME" \
    --paths "$REPO_ROOT/src" \
    --collect-all sqlite_vec \
    --exclude-module pandas \
    --exclude-module pytest \
    --exclude-module scipy \
    --exclude-module torch \
    --distpath "$BUILD_ROOT/helper" \
    --workpath "$BUILD_ROOT/pyinstaller" \
    --specpath "$BUILD_ROOT/spec" \
    "$REPO_ROOT/src/paper_copilot/api/runtime.py"

xcodebuild \
    -project "$REPO_ROOT/apps/macos/PaperCopilot.xcodeproj" \
    -scheme PaperCopilot \
    -configuration Release \
    -destination "platform=macOS,arch=arm64" \
    -derivedDataPath "$DERIVED_DATA" \
    ARCHS=arm64 \
    ONLY_ACTIVE_ARCH=YES \
    CODE_SIGN_IDENTITY=-

mkdir -p "$BUILT_APP/Contents/Resources"
ditto "$HELPER_DIST" "$BUILT_APP/Contents/Resources/$HELPER_NAME"
if [ "$SIGN_IDENTITY" = "-" ]; then
    codesign --force --sign - "$BUILT_APP"
else
    codesign \
        --force \
        --deep \
        --options runtime \
        --timestamp \
        --sign "$SIGN_IDENTITY" \
        "$BUILT_APP"
fi
codesign --verify --deep --strict "$BUILT_APP"
ditto "$BUILT_APP" "$FINAL_APP"

echo "$FINAL_APP"
