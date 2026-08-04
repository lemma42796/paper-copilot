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
MODEL_DIST="$BUILD_ROOT/model-dist/PP-FormulaNet_plus-S"
RUNTIME_ARCHIVE_NAME="formula-ocr-runtime-macos-arm64-$VERSION.zip"
MODEL_ARCHIVE_NAME="formula-ocr-model-PP-FormulaNet_plus-S-$VERSION.zip"
RUNTIME_ARCHIVE_PATH="$BUILD_ROOT/$RUNTIME_ARCHIVE_NAME"
MODEL_ARCHIVE_PATH="$BUILD_ROOT/$MODEL_ARCHIVE_NAME"
MANIFEST_PATH="$BUILD_ROOT/formula-ocr-macos-arm64-manifest.json"
LIBOMP_SOURCE=${FORMULA_OCR_LIBOMP:-}

if [ -z "$MODEL_DIR" ] || [ ! -d "$MODEL_DIR" ]; then
    echo "FORMULA_OCR_MODEL_DIR must point to PP-FormulaNet_plus-S" >&2
    exit 2
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT/spec" "$DIST_ROOT" "$(dirname -- "$MODEL_DIST")"

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
    --collect-all pypdfium2 \
    --collect-all pypdfium2_raw \
    --exclude-module pytest \
    --exclude-module scipy \
    --exclude-module torch \
    --distpath "$DIST_ROOT" \
    --workpath "$BUILD_ROOT/pyinstaller" \
    --specpath "$BUILD_ROOT/spec" \
    "$REPO_ROOT/src/paper_copilot/formula_ocr_helper.py"

SIGN_IDENTITY=${PAPER_COPILOT_SIGN_IDENTITY:--}
if [ -z "$LIBOMP_SOURCE" ] && command -v brew >/dev/null 2>&1; then
    LIBOMP_SOURCE="$(brew --prefix libomp)/lib/libomp.dylib"
fi
if [ -z "$LIBOMP_SOURCE" ] || [ ! -f "$LIBOMP_SOURCE" ]; then
    echo "FORMULA_OCR_LIBOMP must point to an ARM64 libomp.dylib" >&2
    exit 2
fi

# Paddle's macOS wheel references GCC runtime names that PyInstaller does not
# resolve. LLVM libomp implements the required GOMP ABI, while Paddle already
# ships libgcc with the correct install name under a shortened filename.
INTERNAL_DIST="$HELPER_DIST/_internal"
ditto "$LIBOMP_SOURCE" "$INTERNAL_DIST/libgomp.1.dylib"
install_name_tool -id @rpath/libgomp.1.dylib "$INTERNAL_DIST/libgomp.1.dylib"
ln -sfn paddle/libs/libgcc_s.1.dylib "$INTERNAL_DIST/libgcc_s.1.1.dylib"

if [ "$SIGN_IDENTITY" = "-" ]; then
    codesign --force --sign - "$INTERNAL_DIST/libgomp.1.dylib"
    codesign --force --deep --sign - "$HELPER_DIST/FormulaOCRHelper"
else
    codesign \
        --force \
        --options runtime \
        --timestamp \
        --sign "$SIGN_IDENTITY" \
        "$INTERNAL_DIST/libgomp.1.dylib"
    codesign \
        --force \
        --deep \
        --options runtime \
        --timestamp \
        --sign "$SIGN_IDENTITY" \
        "$HELPER_DIST/FormulaOCRHelper"
fi
codesign --verify --strict "$INTERNAL_DIST/libgomp.1.dylib"
codesign --verify --deep --strict "$HELPER_DIST/FormulaOCRHelper"

# Runtime and weights are separately addressable so an exact local artifact can
# be reused without downloading the other half of the component.
ditto -c -k --sequesterRsrc --keepParent "$HELPER_DIST" "$RUNTIME_ARCHIVE_PATH"
ditto "$MODEL_DIR" "$MODEL_DIST"
ditto -c -k --sequesterRsrc --keepParent "$MODEL_DIST" "$MODEL_ARCHIVE_PATH"

RUNTIME_ARCHIVE_SHA256=$(shasum -a 256 "$RUNTIME_ARCHIVE_PATH" | awk '{print $1}')
MODEL_ARCHIVE_SHA256=$(shasum -a 256 "$MODEL_ARCHIVE_PATH" | awk '{print $1}')
RUNTIME_ARCHIVE_BYTES=$(stat -f '%z' "$RUNTIME_ARCHIVE_PATH")
MODEL_ARCHIVE_BYTES=$(stat -f '%z' "$MODEL_ARCHIVE_PATH")
RUNTIME_INSTALLED_BYTES=$(du -sk "$HELPER_DIST" | awk '{print $1 * 1024}')
MODEL_INSTALLED_BYTES=$(du -sk "$MODEL_DIST" | awk '{print $1 * 1024}')

TREE_HASHES=$(uv run python -c '
import hashlib
import os
import sys
from pathlib import Path

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    entries = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    for path in entries:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            record = f"L\0{relative}\0{os.readlink(path)}\n"
        elif path.is_file():
            record = f"F\0{relative}\0{file_sha256(path)}\n"
        elif path.is_dir():
            continue
        else:
            raise SystemExit(f"unsupported artifact entry: {path}")
        digest.update(record.encode("utf-8"))
    return digest.hexdigest()

print(tree_sha256(Path(sys.argv[1])))
print(tree_sha256(Path(sys.argv[2])))
' "$HELPER_DIST" "$MODEL_DIST")
RUNTIME_TREE_SHA256=$(printf '%s\n' "$TREE_HASHES" | sed -n '1p')
MODEL_TREE_SHA256=$(printf '%s\n' "$TREE_HASHES" | sed -n '2p')

# Keep a complete development Helper in dist while release installation remains
# split into independently reusable runtime and model archives.
mkdir -p "$HELPER_DIST/models"
ditto "$MODEL_DIST" "$HELPER_DIST/models/PP-FormulaNet_plus-S"

uv run python -c '
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "schema_version": 2,
    "component": "formula-ocr",
    "version": sys.argv[2],
    "runtime": {
        "archive_url": sys.argv[3],
        "archive_sha256": sys.argv[4],
        "archive_bytes": int(sys.argv[5]),
        "installed_bytes": int(sys.argv[6]),
        "tree_sha256": sys.argv[7],
        "root_directory": "FormulaOCRHelper",
    },
    "model": {
        "archive_url": sys.argv[8],
        "archive_sha256": sys.argv[9],
        "archive_bytes": int(sys.argv[10]),
        "installed_bytes": int(sys.argv[11]),
        "tree_sha256": sys.argv[12],
        "root_directory": "PP-FormulaNet_plus-S",
    },
    "helper_relative_path": "FormulaOCRHelper/FormulaOCRHelper",
    "model_relative_path": "FormulaOCRHelper/models/PP-FormulaNet_plus-S",
}
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
' \
    "$MANIFEST_PATH" \
    "$VERSION" \
    "$RELEASE_BASE_URL/$RUNTIME_ARCHIVE_NAME" \
    "$RUNTIME_ARCHIVE_SHA256" \
    "$RUNTIME_ARCHIVE_BYTES" \
    "$RUNTIME_INSTALLED_BYTES" \
    "$RUNTIME_TREE_SHA256" \
    "$RELEASE_BASE_URL/$MODEL_ARCHIVE_NAME" \
    "$MODEL_ARCHIVE_SHA256" \
    "$MODEL_ARCHIVE_BYTES" \
    "$MODEL_INSTALLED_BYTES" \
    "$MODEL_TREE_SHA256"

echo "$RUNTIME_ARCHIVE_PATH"
echo "$MODEL_ARCHIVE_PATH"
echo "$MANIFEST_PATH"
