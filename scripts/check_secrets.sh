#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

command -v grep >/dev/null 2>&1 || { echo "grep is required" >&2; exit 2; }
git rev-parse --is-inside-work-tree >/dev/null

# Check tracked and new, non-ignored files without printing matching contents.
marker='s''k-'
pattern="(^|[^[:alnum:]_])${marker}[[:alnum:]]"
matches=$(git ls-files --cached --others --exclude-standard |
  while IFS= read -r path; do
    if [ -f "$path" ] && grep -Eq -- "$pattern" "$path"; then
      printf '%s\n' "$path"
    fi
  done)

if [ -n "$matches" ]; then
  printf 'Secret-like API key marker found in:\n%s\n' "$matches" >&2
  exit 1
fi

echo "Secret scan passed."
