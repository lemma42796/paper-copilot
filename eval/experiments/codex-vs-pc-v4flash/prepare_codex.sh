#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
source_checkout=${1:-/Users/a123/Documents/agent学习/codex}
build_root=${2:-/private/tmp/codex-deepseek-library-ablation}

if [[ -e "$build_root" ]]; then
  print -u2 "build target already exists: $build_root"
  exit 1
fi

git clone --shared "$source_checkout" "$build_root"
git -C "$build_root" apply "$script_dir/codex-top-level-library-tools.patch"
cargo build --manifest-path "$build_root/codex-rs/Cargo.toml" --release --package codex-cli

print "$build_root/codex-rs/target/release/codex"
