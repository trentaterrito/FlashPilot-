# Silver Lining: validation-only model-slot reservation

Offline implementation based on f4ddebac53a26e0cc828d65a5cc6da02d6a610ee.
Coordination reservation271; AOL source/device ownership untouched. No device
connection, deployment, activation, inference, or vehicle changes performed.

## Mechanism

Manager retains its existing `ensure_running` supervision. A lease adds only
`modeld` and `modeld_tinygrad` to `not_run`. A grant is sent only after both
managed processes are dead. Manager, card/fingerprinting, controls, panda and
other processes are never stopped by this mechanism. Existing process selection
predicates remain unchanged; with the required empty active-model selections,
native CD210 becomes eligible when the exclusions are removed.

The endpoint is created only when `FLASHPILOT_MODEL_SLOT_VALIDATION=1` is present
at an ordinary manager startup. It is a new private 0700 temporary directory and
Unix socket each time. Linux peer credentials require the same UID as manager.
No persistent Params, model-selection changes, UI, or live injection is used.

A dedicated delegated cgroup-v2 root at
`/sys/fs/cgroup/silver-lining-validation` is a future activation prerequisite.
Manager must be able to create/remove children and write their `cgroup.kill`.
The manager/service itself must NOT be moved into that root's worker children.
No cgroup or service configuration has been created on the device by this work.
Absence of these permissions refuses a lease before suppressing native modeld.
Older kernels without `cgroup.kill` are not qualified; no weaker process-group
fallback is provided.

Each lease creates a unique child cgroup. The client enters it **before** executing
the checker; all descendants inherit membership, including new sessions. Neither
checker nor model runner may migrate outside it. Cleanup kills the entire group,
removes nested empty groups, and removes the lease group before releasing the
slot. A late join after removal fails before exec. If cleanup cannot be proven,
the model slots stay suppressed and manager reports the concrete failure.

EOF, explicit release/abort, malformed protocol, process death, four seconds
without heartbeat, loss of fresh parked eligibility, or the 180-second absolute
limit revoke the lease. Deadlines are evaluated on manager ticks (normally at
most about one additional second; this is not a real-time guarantee).

A subsequent manager startup scans the fixed validation root even if opt-in was
removed. It kills/removes orphaned validation groups before model eligibility.
A scan/cleanup failure suppresses models, not manager or the vehicle interface.
No previous lease is resumed. A reboot removes the kernel cgroups; stale socket
paths cannot grant ownership. Socket errors disable new reservations and allow
cleanup/normal model management after workers are gone.

## Harness integration (future authorized execution only)

Use `model_slot_client.py --endpoint <new endpoint from manager log> -- <command>`
to wrap the existing `shared_model_check.py run` command with the already-prepared
spec/artifact arguments. Do not wrap `transaction.py`: that older orchestration
restarts/reconstructs manager and is not part of this path.

The client's stdin must be supplied by the controlling computer through SSH,
with one small heartbeat line per second for the entire test. Do not run the
heartbeat generator on the Comma or detach it: that would no longer measure the
controlling session. EOF or four seconds without incoming data aborts. SSH
ServerAlive settings may shorten detection but are not the lease clock.
The client closes its lease in finally, and SIGINT/SIGTERM/SIGHUP abort it.
SIGKILL closes the socket in the kernel; manager owns descendant cleanup.

The wrapper returns the checker exit code only after its cgroup disappears.
This confirms worker cleanup, NOT successful native publication recovery.
The prepared native health verifier must still confirm CD210 identity, finite
modelV2/drivingModelData/cameraOdometry, stable 19–21 Hz, and unchanged Lightning
recognition before another reservation. A failed native check stops the gate.

Future order: authorized deployment/opt-in with delegated cgroup preparation;
next ordinary startup (no forced restart); verify normal Lightning/calibration/
READY/Park/parking brake/CD210 baseline; exercise harmless reservation/release,
crash, timeout, abort and session loss; verify native recovery each time. Only
then may separately authorized RDF/OP16 qualification proceed.

## Offline validation and limits

Focused tests exercise lease states, actual `ensure_running` logic with stand-in
processes, worker membership-before-exec, session EOF, orphan cleanup and tooling
failure handling. Model sources, compatibility profiles, selector, controls,
safety and submodule pointers are unchanged.

Mac tests cannot prove Linux SO_PEERCRED, cgroup-v2 delegation/kill, real manager
scheduling, QCOM publications, or Lightning recognition preservation. Those are
explicit on-device reservation/release gates, not claims of this offline commit.
No RDF/OP16 inference or broad vehicle suites were run.

Result: 21 focused tests PASS; independent review VALIDATED OFFLINE after
startup-orphan and persistent-listener-error corrections. Compile/diff checks PASS.
