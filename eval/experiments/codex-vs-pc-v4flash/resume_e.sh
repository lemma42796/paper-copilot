#!/bin/zsh
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  print -u2 "usage: $0 <existing-e-run-root> [--execute]"
  exit 2
fi

run_root=${1:A}
mode=${2:-check}
if [[ "$mode" != "check" && "$mode" != "--execute" ]]; then
  print -u2 "second argument must be --execute"
  exit 2
fi

thread_id="019fc817-5d39-7ab0-94b3-ef07279ef38d"
manifest_sha256="61b0443a057bffe34f6e9cbbe77ed1fe4878e14814fee192ab07a83aa54f0121"
codex_home="$run_root/codex-home"
workspace="$run_root/workspace"
library_environment="$run_root/library-environment"
rollout="$codex_home/sessions/2026/08/03/rollout-2026-08-03T22-46-42-$thread_id.jsonl"
manifest="$library_environment/workspace/research-manifests/current.jsonl"
model_catalog="$codex_home/models.json"
codex_binary=${CODEX_ABLATION_BINARY:-/private/tmp/codex-deepseek-library-ablation/codex-rs/target/release/codex}

for required_path in "$codex_home/config.toml" "$workspace" "$rollout" "$manifest" "$model_catalog"; do
  if [[ ! -e "$required_path" ]]; then
    print -u2 "required E resume artifact is missing: $required_path"
    exit 1
  fi
done

actual_thread_id=$(
  jq -r 'select(.type == "session_meta") | .payload.id' "$rollout" | head -n 1
)
if [[ "$actual_thread_id" != "$thread_id" ]]; then
  print -u2 "unexpected E thread id: $actual_thread_id"
  exit 1
fi

actual_manifest_sha256=$(shasum -a 256 "$manifest" | awk '{print $1}')
if [[ "$actual_manifest_sha256" != "$manifest_sha256" ]]; then
  print -u2 "E manifest SHA-256 mismatch: $actual_manifest_sha256"
  exit 1
fi

if [[ ! -x "$codex_binary" ]]; then
  print -u2 "patched Codex binary is unavailable: $codex_binary"
  exit 1
fi

print "E resume preflight passed"
print "thread_id=$thread_id"
print "manifest_sha256=$manifest_sha256"
print "mode=$mode"
if [[ "$mode" == "check" ]]; then
  print "no Codex process or model request was started"
  exit 0
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

export CODEX_DEEPSEEK_LIBRARY_ABLATION=1
export CODEX_LIBRARY_ENV_ROOT="$library_environment"
export CODEX_LIBRARY_MAX_PAPERS=14
export CODEX_LIBRARY_RESUME_MANIFEST_SHA256="$manifest_sha256"
export CODEX_LIBRARY_SKILL_ALREADY_LOADED=1

cd "$workspace"
CODEX_HOME="$codex_home" "$codex_binary" resume "$thread_id" \
  -c "model_catalog_json=\"$model_catalog\"" \
  -c 'mcp_servers.paper_copilot_library_ablation.env_vars=["PAPER_COPILOT_HOME","PAPER_COPILOT_PDF_DIR","CODEX_LIBRARY_ENV_ROOT","CODEX_LIBRARY_MAX_PAPERS","CODEX_LIBRARY_RESUME_MANIFEST_SHA256","CODEX_LIBRARY_SKILL_ALREADY_LOADED"]'
