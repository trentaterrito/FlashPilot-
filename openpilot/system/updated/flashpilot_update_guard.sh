#!/usr/bin/env bash
# Launch-time defense against an already-finalized ancestor or divergent overlay.
set -euo pipefail

installed_repo="$1"
staged_repo="$2"
installed=$(git -C "$installed_repo" rev-parse --verify 'HEAD^{commit}') || exit 1
staged=$(git -C "$staged_repo" rev-parse --verify 'HEAD^{commit}') || exit 1
staged_branch=$(git -C "$staged_repo" symbolic-ref --quiet --short HEAD) || exit 1

[[ "$staged_branch" == "flashpilot-v2-deploy" ]] || exit 1
[[ "$installed" != "$staged" ]] || exit 1
git -C "$staged_repo" merge-base --is-ancestor "$installed" "$staged" || exit 1
