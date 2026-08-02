#!/bin/zsh
set -euo pipefail

if [[ $# -ne 2 ]]; then
  print -u2 "usage: $0 <b|c> <persistent-runs-root>"
  exit 2
fi

lane=$1
runs_root=$2
if [[ "$lane" != "b" && "$lane" != "c" ]]; then
  print -u2 "lane must be b or c"
  exit 2
fi
if [[ -n "${CODEX_THREAD_ID:-}" || -n "${CODEX_INTERNAL_ORIGINATOR_OVERRIDE:-}" ]]; then
  print -u2 "refusing to inherit a parent Codex task; launch from a standalone terminal"
  exit 2
fi
if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  print -u2 "DEEPSEEK_API_KEY is not present in this process environment"
  exit 2
fi
if [[ -z "${PAPER_COPILOT_HOME:-}" || -z "${PAPER_COPILOT_PDF_DIR:-}" ]]; then
  print -u2 "PAPER_COPILOT_HOME and PAPER_COPILOT_PDF_DIR are required"
  exit 2
fi

script_dir=${0:A:h}
codex_binary=${CODEX_ABLATION_BINARY:-/private/tmp/codex-deepseek-library-ablation/codex-rs/target/release/codex}
if [[ ! -x "$codex_binary" ]]; then
  print -u2 "patched Codex binary is unavailable: $codex_binary"
  exit 2
fi

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
run_id="${timestamp}-lane-${lane}-$(uuidgen | tr '[:upper:]' '[:lower:]')"
run_root="${runs_root:A}/$run_id"
codex_home="$run_root/codex-home"
workspace="$run_root/workspace"
library_environment="$run_root/library-environment"
model_catalog="$codex_home/models.json"
mkdir -p "$codex_home" "$workspace" "$library_environment"
cp "$script_dir/config-$lane.toml" "$codex_home/config.toml"
"/Users/a123/code/paper-copilot/.venv/bin/python" \
  "$script_dir/prepare_model_catalog.py" \
  "/Users/a123/.codex-deepseek/models.json" \
  "$model_catalog"

export CODEX_DEEPSEEK_LIBRARY_ABLATION=1
export CODEX_LIBRARY_ENV_ROOT="$library_environment"
export CODEX_LIBRARY_MAX_PAPERS=${CODEX_LIBRARY_MAX_PAPERS:-14}

print "run_root=$run_root"
print "lane=$lane"
print "query execution has not started; enter the frozen query in the Codex TUI"
cd "$workspace"
CODEX_HOME="$codex_home" "$codex_binary" \
  -c "model_catalog_json=\"$model_catalog\""
