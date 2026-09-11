#!/bin/bash
set -Eeuo pipefail
export GIT_TERMINAL_PROMPT=0
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
readonly ROOT=/data
readonly REPO=https://github.com/trentaterrito/FlashPilot-.git
readonly BRANCH=flashpilot-dev
readonly SHA=dfd4b419f73b2bccbfd0e4d7007124a68ae04c71
readonly SSH_PUBLIC_KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMd/x4lkzsLcefKb8A46npmgxxo5dda7Sw2DnuyY7Luz trentterrito@gmail.com'
readonly LOG="$ROOT/flashpilot-install-$SHA.log"
exec >>"$LOG" 2>&1
printf 'BEGIN %s repo=%s branch=%s sha=%s\n' "$(date -u +%FT%TZ)" "$REPO" "$BRANCH" "$SHA"
fail() { echo "FAIL: $*"; exit 1; }
# Only the clean setup flow may install. Never replace a running checkout.
[[ -f /AGNOS ]] || fail 'AGNOS required'
[[ ! -e "$ROOT/continue.sh" && ! -L "$ROOT/continue.sh" ]] || fail 'existing launcher: use normal uninstall/setup first'
[[ ! -e "$ROOT/openpilot" && ! -L "$ROOT/openpilot" ]] || fail 'existing checkout: use normal uninstall/setup first'
[[ ! -e "$ROOT/continue.sh.new" && ! -L "$ROOT/continue.sh.new" ]] || fail 'existing pending launcher'
command -v git >/dev/null || fail 'git unavailable'
git lfs version || fail 'managed git-lfs unavailable'
stage=$(mktemp -d "$ROOT/.flashpilot-install.XXXXXXXX")
activated=0
moved=0
cleanup() {
  rc=$?
  trap - EXIT
  if (( activated == 0 )); then
    rm -f "$stage/continue.sh"
    if (( moved == 1 )); then
      # Keep a complete failed candidate, but never leave it active.
      mv "$ROOT/openpilot" "$stage/failed-openpilot" || echo 'FAIL: failed candidate could not be deactivated'
    fi
    echo "FAIL/PENDING: exit=$rc stage=$stage; no launcher published"
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Fetch the immutable commit directly. The public branch may legitimately move.
mkdir "$stage/openpilot"
git -C "$stage/openpilot" init
git -C "$stage/openpilot" remote add origin "$REPO"
GIT_LFS_SKIP_SMUDGE=1 git -C "$stage/openpilot" fetch --depth=1 origin "$SHA"
cd "$stage/openpilot"
[[ $(git remote get-url origin) == "$REPO" ]] || fail 'origin mismatch'
[[ $(git rev-parse FETCH_HEAD) == "$SHA" ]] || fail 'immutable fetch SHA mismatch'
GIT_LFS_SKIP_SMUDGE=1 git checkout -B "$BRANCH" "$SHA"
[[ $(git symbolic-ref --short HEAD) == "$BRANCH" ]] || fail 'branch mismatch'
[[ $(git rev-parse HEAD) == "$SHA" ]] || fail 'checkout SHA mismatch'
git submodule update --init --recursive
check_pin() {
  [[ $(git -C "$1" rev-parse HEAD) == "$2" ]] || fail "submodule SHA mismatch: $1"
  printf 'PIN %s %s\n' "$1" "$2"
}
check_pin opendbc_repo 42fa6447ed0ff9a0497a14ca136ea45d923c1106
check_pin panda 8bcae70c896bf3aee98b28641755f82b4aa5bf8b
check_pin msgq_repo 0e266c1dbcf7328beee3e57b4a8688555387c877
check_pin rednose_repo 28d4a7f69e80e1c3e0d24ca0733d7daeaeade3d0
check_pin teleoprtc_repo 1aa8fc433bef1519a95c0700c96258c3be6dfb34
check_pin tinygrad_repo e837e367aac9e1a66e689f4f32ce20ca9367df13
submodules=$(git submodule status --recursive)
printf '%s\n' "$submodules"
if printf '%s\n' "$submodules" | grep -q '^[+-U]'; then fail 'recursive submodule mismatch'; fi
git lfs pull
git lfs fsck --objects
lfs_files=$(git lfs ls-files)
if printf '%s\n' "$lfs_files" | grep -q '^[0-9a-f]* - '; then fail 'unmaterialized LFS pointers'; fi
git submodule foreach --recursive 'git lfs pull && git lfs fsck --objects && files=$(git lfs ls-files) && ! printf "%s\n" "$files" | grep -q "^[0-9a-f]* - " && test -z "$(git status --porcelain=v1 --untracked-files=all)"'
[[ -z $(git status --porcelain=v1 --untracked-files=all) ]] || fail 'dirty staged checkout'
[[ -x launch_openpilot.sh ]] || fail 'missing normal managed launcher'
[[ $(git rev-parse HEAD) == "$SHA" ]] || fail 'final SHA mismatch'
printf 'VERIFIED repo=%s branch=%s HEAD=%s\n' "$REPO" "$BRANCH" "$SHA"
# Standard installer handoff. No settings, source patches or runtime operations.
printf '#!/usr/bin/env bash\n\nexport FLASHPILOT_ANGLE_ENABLED=1\n\ncd /data/openpilot\nexec ./launch_openpilot.sh\n' > "$stage/continue.sh"
chmod 755 "$stage/continue.sh"
[[ ! -e "$ROOT/openpilot" && ! -L "$ROOT/openpilot" ]] || fail 'checkout appeared during install'
[[ ! -e "$ROOT/continue.sh" && ! -L "$ROOT/continue.sh" ]] || fail 'launcher appeared during install'
mv "$stage/openpilot" "$ROOT/openpilot"
moved=1
[[ $(git -C "$ROOT/openpilot" symbolic-ref --short HEAD) == "$BRANCH" ]] || fail 'active branch mismatch'
[[ $(git -C "$ROOT/openpilot" rev-parse HEAD) == "$SHA" ]] || fail 'active SHA mismatch'
[[ -z $(git -C "$ROOT/openpilot" status --porcelain=v1 --untracked-files=all) ]] || fail 'active checkout dirty'
# Diagnostic recovery only: preserve the owner's existing SSH access through onboarding.
[[ -d "$ROOT/params/d" ]] || fail 'setup Params unavailable for diagnostic SSH access'
printf '%s\n' "$SSH_PUBLIC_KEY" > "$ROOT/params/d/GithubSshKeys"
printf '1' > "$ROOT/params/d/SshEnabled"
chmod 600 "$ROOT/params/d/GithubSshKeys" "$ROOT/params/d/SshEnabled"
sync
mv "$stage/continue.sh" "$ROOT/continue.sh"
activated=1
sync
printf 'CHECKOUT PASS. MANAGED_BOOTSTRAP PENDING: comma.service/comma.sh owns startup. Manager/UI/modeld health is NOT yet verified.\n'
# Never launch FlashPilot manually or install a monitor/service. The OS sees continue.sh.
