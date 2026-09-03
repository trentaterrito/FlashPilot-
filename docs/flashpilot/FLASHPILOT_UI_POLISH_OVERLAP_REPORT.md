# FlashPilot UI Polish: Scope, Branch Setup, and Codex Overlap Report

Branch: `claude/flashpilot-ui-polish`, created from `origin/flashpilot-dev`
@ `036430eb628234e0f75d476e2a3a1b6db72491ee` ("Toggle Lightning Experimental
mode with three-second distance hold"). Submodules pinned exactly as that
commit records them (no bump): `opendbc_repo` @ `9371c42ba79067f86d172716637a5e0cf7451b9e`,
`panda` @ `75aa44bec9140849868239b1f1e3f22624adb8fe`.

This is a UI-only workstream: implement the current UX backlog (large mode
notifications, a Ford cluster display audit, a lead-marker audit) without
touching vehicle-control logic, so it merges cleanly against Codex's active
driving-behavior work rather than fighting it.

## Pre-flight overlap check

Before writing any code, `git fetch origin --prune` (superproject) and a
submodule fetch of `opendbc_repo` were used to enumerate every branch on both
remotes and check which are already fully merged into `flashpilot-dev` vs.
still active (diverged, not yet merged):

**Superproject (`trentaterrito/FlashPilot-`) branches, relative to
`flashpilot-dev`:**

| Branch | Status |
|---|---|
| `codex/experimental-distance-hold` | fully merged |
| `codex/flashpilot-first-drive-analyzer` | fully merged |
| `codex/flashpilot-parked-development` | fully merged |
| `codex/lightning-first-vehicle-test` | fully merged |
| `codex/flashpilot-mads-sunnypilot` | **active** (2 commits ahead) |
| `codex/mads-rc-20260903` | **active** (18 commits ahead) |
| `codex/mads-rc-integrated-20260903` | **active** (19 commits ahead) |
| `codex/mads-set-engagement-20260903` | **active** (20 commits ahead) |

**Files the active branches touch** (diffstat against their merge-base with
`flashpilot-dev`), superproject side:

```
.gitmodules, README.md, docs/**  (MADS design/validation/RC docs, large)
opendbc_repo, panda              (submodule pointer bumps)
openpilot/cereal/custom.capnp, openpilot/cereal/log.capnp
openpilot/common/params_keys.h
openpilot/selfdrive/car/card.py, openpilot/selfdrive/car/flashpilot_mads.py
openpilot/selfdrive/controls/controlsd.py
openpilot/selfdrive/controls/lib/flashpilot_mads.py
openpilot/selfdrive/monitoring/{dmonitoringd,flashpilot_mads,policy}.py
openpilot/selfdrive/pandad/{mads_lifecycle.h,panda.cc,panda.h,pandad.cc}
openpilot/selfdrive/selfdrived/selfdrived.py
openpilot/selfdrive/ui/mici/onroad/{alert_renderer,hud_renderer}.py
openpilot/selfdrive/ui/onroad/{alert_renderer,hud_renderer}.py
openpilot/selfdrive/ui/onroad/mads_feedback.py   (new)
openpilot/selfdrive/ui/ui_state.py
openpilot/sunnypilot/**          (new, vendored)
tools/mads/**                    (large, new)
```

**`opendbc_repo` fork (`trentaterrito/flashpilot-opendbc`) branches, relative
to the `9371c42b` commit this branch's gitlink is pinned to:**

| Branch | Status |
|---|---|
| `codex/lightning-first-vehicle-test` | fully merged |
| `codex/flashpilot-mads-sunnypilot` | active, docs-only (`README.md`, 2 new `docs/FLASHPILOT_MADS_*.md`) |
| `codex/mads-rc-20260903` | active: `opendbc/car/ford/values.py`, `opendbc/safety/modes/ford.h`, `opendbc/safety/modes/ford_sunnypilot_mads.h`, MADS safety tests/data |
| `codex/mads-set-engagement-20260903` | active: same file set as above |

## What this means for this branch

- `opendbc`, `panda`, and everything Ford-control-related are **unconditionally
  out of scope** for this branch per its own instructions -- not merely
  "avoid if Codex is touching it." Nothing in `opendbc_repo`, `panda`, or
  `opendbc/car/ford/{carcontroller,fordcan}.py` specifically was read for any
  purpose other than the UX 2 audit (see below), and nothing in any of those
  was written to. The submodule gitlinks are untouched (still exactly what
  `flashpilot-dev`'s own base commit recorded).
- `openpilot/selfdrive/ui/ui_state.py`, both `alert_renderer.py`s, both
  `hud_renderer.py`s, and `openpilot/selfdrive/selfdrived/selfdrived.py` are
  under active, non-trivial concurrent modification by the MADS branches
  above (confirmed by direct diff, not assumption -- e.g. `ui_state.py`
  currently gains a `mads_display`/`MadsFeedback` field and an `update_feedback()`
  call from `codex/mads-set-engagement-20260903`). **None of these were
  touched.** The reusable mode-notification work (UX 1) was deliberately
  designed around this: `mode_notification.py` is a new, standalone file, and
  its only call site (`augmented_road_view.py`) is not on the above list.
- `README.md` is also touched by active MADS work (`+6` lines in
  `codex/mads-set-engagement-20260903`) and by several already-merged
  commits; it was left untouched here rather than adding a doc-index entry
  that could conflict with an in-flight edit. The three new docs from this
  branch are self-contained and cross-link each other instead.

## What this branch actually changed

| Area | Files | Notes |
|---|---|---|
| UX 1 (implemented) | `openpilot/selfdrive/ui/mici/onroad/mode_notification.py` (new), `augmented_road_view.py` (small edit), `mici/tests/test_mode_notification.py` (new), `mici/tests/test_experimental_notification.py` (test-only update) | See `FLASHPILOT_UI_MODE_NOTIFICATION.md`. |
| UX 2 (audited, blocked) | none (docs only) | See `FLASHPILOT_UI_FORD_HANDS_FREE_CLUSTER_AUDIT.md` -- implementation requires `opendbc`, which is out of scope; STOPPED per the task's own instruction rather than proceeding. |
| UX 3 (audited) | none | See `FLASHPILOT_UI_LEAD_MARKER_AUDIT.md` -- recommendation is NO CHANGE. |

Confirmed **not** touched, per the task's explicit list: `opendbc`, `panda`,
Ford carcontroller, the path-angle implementation, radar parsing, the
longitudinal planner/MPC, lane-change control logic, engagement/safety logic,
stop/launch behavior, or any file identified above as part of Codex's active
curve/nudgeless/longitudinal/MADS work.

## Test environment note

This sandbox has no GPU/display and, initially, none of `pyray`
(`comma-deps-raylib`), `pycapnp`, `pyzmq`, `zstandard`, `setproctitle`, or a
built `msgq` native extension. A scratch venv
(`/tmp/.../scratchpad/ui-venv`, Python 3.12) was built up with the
pip-installable pieces (`comma-deps-raylib`, `pycapnp`, `pyzmq`,
`zstandard`, `setproctitle`, `cython`) plus an editable install of the
`msgq_repo` submodule (initialized read-only for this purpose only) --
this was enough to import and test everything this branch touches or added,
*except* one pre-existing test
(`test_actual_renderer_gates_and_alert_priority` in
`test_experimental_notification.py`, all 8 of its parametrizations), which
imports `augmented_road_view.py` -&gt; `ui_state.py` -&gt; `cereal.messaging` -&gt;
`msgq.ipc_pyx`, a Cython extension that requires a full `scons` + libzmq
native build this sandbox doesn't have (no `scons`, no `libzmq` headers).
This is confirmed pre-existing and unrelated to this branch's change (the
import fails at `ui_state.py`'s own top-level `cereal` import, before
reaching any code this branch modified). See each area's own doc for exactly
which tests did run.
