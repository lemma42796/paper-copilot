#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
VERSION=${FORMULA_OCR_COMPONENT_VERSION:-1.0.0}
MODEL_DIR=${FORMULA_OCR_MODEL_DIR:-}
RELEASE_BASE_URL=${FORMULA_OCR_RELEASE_BASE_URL:-https://github.com/lemma42796/paper-copilot/releases/download/formula-ocr-v1}
BUILD_ROOT="$REPO_ROOT/build/formula-ocr-component"
DIST_ROOT="$BUILD_ROOT/dist"
HELPER_DIST="$DIST_ROOT/FormulaOCRHelper"
ARCHIVE_NAME="formula-ocr-macos-arm64-$VERSION.zip"
ARCHIVE_PATH="$BUILD_ROOT/$ARCHIVE_NAME"
MANIFEST_PATH="$BUILD_ROOT/formula-ocr-macos-arm64-manifest.json"

if [ -z "$MODEL_DIR" ] || [ ! -d "$MODEL_DIR" ]; then
    echo "FORMULA_OCR_MODEL_DIR must point to PP-FormulaNet_plus-S" >&2
    exit 2
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT/spec" "$DIST_ROOT"

cd "$REPO_ROOT"
uv run --group dev --group formula-ocr pyinstaller \
    --noconfirm \
    --clean \
    --onedir \
    --name FormulaOCRHelper \
    --paths "$REPO_ROOT/src" \
    --collect-all paddle \
    --collect-all paddleocr \
    --collect-all paddlex \
    --collect-all cv2 \
    --collect-all tokenizers \
    --exclude-module pandas \
    --exclude-module pytest \
    --exclude-module scipy \
    --exclude-module torch \
    --distpath "$DIST_ROOT" \
    --workpath "$BUILD_ROOT/pyinstaller" \
    --specpath "$BUILD_ROOT/spec" \
    "$REPO_ROOT/src/paper_copilot/formula_ocr_helper.py"

mkdir -p "$HELPER_DIST/models"
ditto "$MODEL_DIR" "$HELPER_DIST/models/PP-FormulaNet_plus-S"

SIGN_IDENTITY=${PAPER_COPILOT_SIGN_IDENTITY:--}
if [ "$SIGN_IDENTITY" = "-" ]; then
    codesign --force --deep --sign - "$HELPER_DIST/FormulaOCRHelper"
else
    codesign \
        --force \
        --deep \
        --options runtime \
        --timestamp \
        --sign "$SIGN_IDENTITY" \
        "$HELPER_DIST/FormulaOCRHelper"
fi
codesign --verify --deep --strict "$HELPER_DIST/FormulaOCRHelper"

ditto -c -k --sequesterRsrc --keepParent "$HELPER_DIST" "$ARCHIVE_PATH"
ARCHIVE_SHA256=$(shasum -a 256 "$ARCHIVE_PATH" | awk '{print $1}')
ARCHIVE_BYTES=$(stat -f '%z' "$ARCHIVE_PATH")
INSTALLED_BYTES=$(du -sk "$HELPER_DIST" | awk '{print $1 * 1024}')

uv run python -c '
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "schema_version": 1,
    "component": "formula-ocr",
    "version": sys.argv[2],
    "archive_url": sys.argv[3],
    "archive_sha256": sys.argv[4],
    "archive_bytes": int(sys.argv[5]),
    "installed_bytes": int(sys.argv[6]),
    "helper_relative_path": "FormulaOCRHelper/FormulaOCRHelper",
}
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
' \
    "$MANIFEST_PATH" \
    "$VERSION" \
    "$RELEASE_BASE_URL/$ARCHIVE_NAME" \
    "$ARCHIVE_SHA256" \
    "$ARCHIVE_BYTES" \
    "$INSTALLED_BYTES"

echo "$ARCHIVE_PATH"
echo "$MANIFEST_PATH"
