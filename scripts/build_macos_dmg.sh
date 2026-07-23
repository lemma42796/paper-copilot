#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
DIST_ROOT="$REPO_ROOT/dist/macos"
APP_PATH="$DIST_ROOT/PaperCopilot.app"
DMG_PATH="$DIST_ROOT/PaperCopilot-arm64.dmg"
STAGING_ROOT="$REPO_ROOT/build/macos-dmg"
SIGN_IDENTITY="${PAPER_COPILOT_SIGN_IDENTITY:--}"
NOTARY_PROFILE="${PAPER_COPILOT_NOTARY_PROFILE:-}"

"$SCRIPT_DIR/build_macos_app.sh"

rm -rf "$STAGING_ROOT" "$DMG_PATH"
mkdir -p "$STAGING_ROOT"
ditto "$APP_PATH" "$STAGING_ROOT/PaperCopilot.app"
ln -s /Applications "$STAGING_ROOT/Applications"

hdiutil create \
    -volname "Paper Copilot" \
    -srcfolder "$STAGING_ROOT" \
    -format UDZO \
    -ov \
    "$DMG_PATH"

if [ "$SIGN_IDENTITY" != "-" ]; then
    codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG_PATH"
    codesign --verify --strict "$DMG_PATH"
fi

if [ -n "$NOTARY_PROFILE" ]; then
    if [ "$SIGN_IDENTITY" = "-" ]; then
        echo "PAPER_COPILOT_NOTARY_PROFILE requires PAPER_COPILOT_SIGN_IDENTITY" >&2
        exit 1
    fi
    xcrun notarytool submit "$DMG_PATH" \
        --keychain-profile "$NOTARY_PROFILE" \
        --wait
    xcrun stapler staple "$DMG_PATH"
    xcrun stapler validate "$DMG_PATH"
fi

echo "$DMG_PATH"
