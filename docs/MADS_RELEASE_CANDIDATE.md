# FlashPilot MADS — install, verify, rollback

Candidate is default OFF, locally committed, not deployed. All source SHAs are
in the release package `MANIFEST.json`; code implementation is
`ce8b1eaa7272dc61e1120c1b2542e7b7ef027c1d`, opendbc
`11cc1647a6b63223cc7d95147fd487727f60f744`, panda
`612c1980c59c7bce01cf320ad6779d2c9688f910`. A documentation-only descendant may
be the packaged superproject HEAD. No source dependency on another local tree.

**Park, ignition OFF, never execute state changes while driving.** Installation
will update panda firmware when normal pandad starts; no firmware was flashed
during preparation. A full Comma reboot is not required. Preserve the currently
working tree and its firmware locally. Do not uninstall/delete StarPilot or any
older rollback tree to make this installation fit.

## Release package / transfer (Mac)

Prepared package directory:
`work/releases/flashpilot-mads-20260903/` under the workspace. Contains seven
self-contained Git bundles, the existing upstream LFS objects, SHA256SUMS and
MANIFEST.json. No Mac native binaries are installed on the Comma. Public remotes
do not yet contain these commits; do not replace this with git pull or an
upstream panda submodule checkout.

Use the current SSH hostname/IP, not an old address assumed by this document:

```sh
COMMA_HOST=comma@YOUR_CURRENT_COMMA_IP
scp -r '/Users/trentterrito/Documents/ChatGPT/OpenAi, BluePilot/work/releases/flashpilot-mads-20260903' "$COMMA_HOST:/data/"
ssh "$COMMA_HOST"
```

## Parked preflight (existing SSH session on Comma)

Run from the existing working installation. IsOffroad alone is not evidence of
ignition/no-output state; require live device/panda observations as well.

```sh
cd /data/openpilot
/usr/local/venv/bin/python - <<'PY'
from openpilot.common.params import Params
from openpilot.cereal import messaging
s = messaging.SubMaster(['deviceState', 'pandaStates'])
for _ in range(6):
  s.update(500)
assert Params().get_bool('IsOffroad'), 'Not offroad'
assert s.all_checks(), 'No fresh valid device/panda state'
assert not s['deviceState'].started, 'Vehicle started'
assert len(s['pandaStates']) == 1, 'Expected one panda'
for p in s['pandaStates']:
  assert not p.ignitionLine and not p.ignitionCan, 'Ignition must be OFF'
  assert not p.controlsAllowed, 'Controls permission present'
  assert str(p.safetyModel) in ('silent', 'noOutput'), 'Not in no-output state'
print('PARKED PRECHECK PASS — driver must independently confirm Park')
PY
df -h /data
command -v git-lfs
test -x /usr/local/venv/bin/scons
test ! -e /data/openpilot-pre-mads-20260903
test ! -e /data/openpilot-mads-candidate
```

Stop on any failure. Allow at least5GB free for package, staged source and build;
this is a conservative working allowance, not permission to remove old trees.

## Stage and verify source — original installation still intact

```sh
set -e
cd /data/flashpilot-mads-20260903
sha256sum -c SHA256SUMS
export GIT_LFS_SKIP_SMUDGE=1
git clone flashpilot.bundle /data/openpilot-mads-candidate
for name in opendbc_repo panda msgq_repo rednose_repo teleoprtc_repo tinygrad_repo; do
  git clone "$name.bundle" "/data/openpilot-mads-candidate/$name"
done
tar -xzf lfs-objects.tar.gz -C /data/openpilot-mads-candidate/.git
cd /data/openpilot-mads-candidate
git lfs install --local --skip-smudge
git lfs checkout
git lfs fsck
/usr/local/venv/bin/python - <<'PY'
import json, subprocess
from pathlib import Path
m = json.loads(Path('/data/flashpilot-mads-20260903/MANIFEST.json').read_text())
for path, expected in m['commits'].items():
  actual = subprocess.check_output(['git', '-C', path, 'rev-parse', 'HEAD'], text=True).strip()
  assert actual == expected, (path, actual, expected)
  assert not subprocess.check_output(['git', '-C', path, 'status', '--porcelain']), path
print('EXACT SOURCE AND CLEAN TREES VERIFIED')
PY
# HEAD is deliberately detached: do not enable automatic branch updates for
# this local test candidate or replace its pinned submodule revisions.
# Preserve the currently working OS/launcher contract; do not auto-upgrade AGNOS.
cmp launch_env.sh /data/openpilot/launch_env.sh
cmp launch_chffrplus.sh /data/openpilot/launch_chffrplus.sh
```

If either launcher comparison fails, stop rather than override AGNOS_VERSION or
run an updater. Source requires its existing Comma4/AGNOS environment; preserve
`/data/continue.sh`, calibration and all existing settings. This stage has not
changed `/data/openpilot` or started candidate pandad.

## Build and activate with local rollback retained

Repeat the live preflight immediately before stopping comma. The Comma4's
offroad power saving can offline CPU7 used by model compilation. The temporary
CPU7 adjustment below is build-only and restores its entry state; it changes no
driving logic. Do not force onroad or run pandad manually to make a build work.

```sh
set -e
sudo systemctl stop comma
cp -p /data/continue.sh /data/flashpilot-mads-20260903/continue-before.sh
cd /data/openpilot-mads-candidate
export PATH="/usr/local/venv/bin:$PATH"
export PYTHONPATH="$PWD:$PWD/opendbc_repo:$PWD/msgq_repo:$PWD/rednose_repo:$PWD/teleoprtc_repo:$PWD/tinygrad_repo"
MADS_CPU7_BEFORE=$(cat /sys/devices/system/cpu/cpu7/online)
trap 'printf "%s\n" "$MADS_CPU7_BEFORE" | sudo tee /sys/devices/system/cpu/cpu7/online >/dev/null' EXIT
printf '1\n' | sudo tee /sys/devices/system/cpu/cpu7/online >/dev/null
scons -j4
scons -C panda -j4 board/obj/panda_h7.bin.signed
printf '%s\n' "$MADS_CPU7_BEFORE" | sudo tee /sys/devices/system/cpu/cpu7/online >/dev/null
trap - EXIT
/usr/local/venv/bin/python - <<'PY'
from openpilot.common.params import Params
p = Params()
assert p.get_bool('IsOffroad')
p.put_bool('FlashPilotMads', False, block=True)
PY
cd /data
mv /data/openpilot /data/openpilot-pre-mads-20260903
mv /data/openpilot-mads-candidate /data/openpilot
unset PYTHONPATH
sudo systemctl start comma
systemctl is-active comma
```

If build fails before the two moves, the original tree is still in place:
restore CPU7 with the trap and `sudo systemctl start comma`; do not activate the
candidate. If activation/startup fails, use full rollback below. On success,
normal pandad verifies the expected firmware signature and flashes the matching
H7 image if necessary. This is an intentional firmware change. Keep ignition OFF
until startup completes; do not unplug power during firmware update. Review
`journalctl -u comma -n 100 --no-pager` and `/tmp/launch_log` for build/firmware errors.

Candidate remains MADS OFF. The existing external
`FLASHPILOT_ANGLE_ENABLED=1` launcher setting must already be present; this
procedure does not change path-angle tuning, launcher settings or radar gates.

## Enable / disable MADS (parked, ignition OFF)

Run the live preflight again, then:

```sh
cd /data/openpilot
/usr/local/venv/bin/python -c "from openpilot.common.params import Params; p=Params(); assert p.get_bool('IsOffroad'); p.put_bool('FlashPilotMads', True, block=True)"
sudo systemctl restart comma
```

To disable, same command with `False`, followed by the same service restart.
`FlashPilotMads` is persistent/development-only, defaultFalse, read once by card
before publishing CarParams. It is not live-reloaded. Restart is required; a full
Comma reboot is not. Turn ignition ON only afterward for the stationary check.
No command directly grants panda authorization; a fresh physical TJA press is
still required after all operating conditions are valid.

## Verify before driving

Offroad only confirms the requested setting; panda correctly stays noOutput and
MADS authorization false. After ignition ON **while still in Park**, run:

```sh
cd /data/openpilot
/usr/local/venv/bin/python - <<'PY'
from openpilot.common.params import Params
from openpilot.cereal import messaging
from opendbc.car.structs import CarParams
p = Params()
print('Requested Param:', p.get_bool('FlashPilotMads'))
raw = p.get('CarParams')
assert raw is not None
with CarParams.from_bytes(raw) as cp:
  print('Fingerprint:', cp.carFingerprint)
  print('Safety:', [(str(x.safetyModel), x.safetyParam) for x in cp.safetyConfigs])
  assert cp.carFingerprint == 'FORD_F_150_LIGHTNING_MK1'
  assert len(cp.safetyConfigs) == 1 and cp.safetyConfigs[0].safetyParam & 4
s = messaging.SubMaster(['pandaStates', 'controlsState', 'carControl', 'carState'])
for _ in range(6):
  s.update(500)
assert s.all_checks(), 'No fresh valid driving-process state; do not drive'
assert len(s['pandaStates']) == 1
x = s['pandaStates'][0]
assert x.madsSafetyEnabled and not x.safetyRxChecksInvalid and not x.faults
assert str(s['carState'].gearShifter) == 'park' and abs(s['carState'].vEgo) < .1
cc, cs = s['carControl'], s['controlsState']
print('Panda selected:', x.madsSafetyEnabled)
print('REQ/PANDA/AUTH/LAT/LONG:', cs.madsState.enabled, x.controlsAllowedLateral,
      cs.madsAuthorized, cc.latActive, cc.longActive)
assert not x.controlsAllowedLateral and not cc.latActive and not cc.longActive
print('PARKED CHECK PASS; no permission granted')
PY
```

Expected: requestedTrue; Lightning fingerprint; Ford safetyParam6 or7 (depending
on existing long selection), panda selectedTrue; all request/authorization/active
valuesFalse in Park. If selector did not take effect, do not force a fingerprint,
safety mode or Params readiness. Check path-angle environment, exact firmware,
correct non-passive fingerprint and restart instead.

## Emergency / full rollback — offline

Stop safely, Park and ignition OFF before running. No network is needed after
the old working tree is retained. Do not erase failed-candidate logs.

```sh
set -e
test -d /data/openpilot-pre-mads-20260903
test ! -e /data/openpilot-mads-failed-20260903
sudo systemctl stop comma
# Remove only the new selection; old baseline need not know this Param name.
rm -f /data/params/d/FlashPilotMads
cd /data
mv /data/openpilot /data/openpilot-mads-failed-20260903
mv /data/openpilot-pre-mads-20260903 /data/openpilot
sudo systemctl start comma
systemctl is-active comma
```

The old tree includes its previous panda source, signed firmware and native
outputs. Its normal pandad restores/verifies its own expected firmware; allow
that process to finish before powering off or driving. Launcher and other Params
were never replaced. If automatic firmware recovery fails, remain parked and
use the retained tree's recovery procedure; do not bypass signature or safety
checks. Removing only the MADS Param also prevents accidental future re-enabling.

## First vehicle test card — controlled area only

Hands ready; start at low speed in a quiet controlled area. No fault injection
or resets while moving. Stop immediately for unexpected direction, oscillation,
fault, poor override, wrong axis engagement or authorization disagreement.

1. Parked: correct fingerprint, no faults, all control states OFF; TJA in Park
   must not activate steering.
2. Drive, cruise OFF: fresh TJA release/press → lateral ON, longitudinal OFF.
3. Apply accelerator manually → lateral remains ON, long remains OFF.
4. Manual brake → lateral remains ON; long inactive; brake release does not
   start long.
5. Explicitly engage cruise/long → both ON. Brake cancels long only.
6. Re-engage long, then cruise CANCEL → lateral remains ON, long OFF.
7. TJA → lateral OFF. Cruise must not silently re-enable lateral.
8. Gentle manual steering override remains usable. Stop if any steering fault
   occurs; it must revoke lateral. Do not induce a fault while driving.
9. After stopping, ignition OFF/restart → no stale authorization or auto-engage.

Preserve the complete route/rlogs, source SHAs, Param setting, bookmarks and
driver observations. Inspect controlsState requested/authorized/state/countdown,
pandaStates selected/lateral/ordinary permission, carControl latActive/longActive,
carState pedals/TJA/gear/faults, plus startup logs. No radar, tuning or general
driving-comfort evaluation is part of this first MADS test.
