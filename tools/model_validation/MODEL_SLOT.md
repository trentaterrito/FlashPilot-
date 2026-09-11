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

The cleanup backend uses systemd transient services under the dedicated
`/sys/fs/cgroup/silverliningvalidation.slice`. Each service has a unique UUID,
User=comma, Delegate=yes, KillMode=control-group, TimeoutStopSec=2,
SendSIGKILL=yes, Restart=no and RuntimeMaxSec=185. The device's systemd255/kernel
4.9.103 combination supports this; cgroup.kill and freezer controls are not used.

The validation-only commands require existing noninteractive sudo authority for
systemd-run/systemctl and the self-entry helper. No persistent service, permission
rule, cgroup delegation setup or production launcher change is installed here.
Only the startup opt-in is still needed after separately authorized deployment.

A small privileged helper validates the service and originating sudo identity,
moves **only itself** into the domain, drops to the original non-root account,
then executes the worker. This is required because the kernel denies migration
across cgroups to a normal user even when the destination is delegated. It never
moves an externally supplied PID or runs the model as root. Descendants inherit
the domain, including children that start new process sessions.

Cleanup validates the exact unit name, InvocationID, dedicated cgroup path,
owner and cleanup properties before requesting systemd stop. It never signals
PID snapshots or matches production process names. Completion requires both a
terminal/absent service and a disappeared cgroup. A partially created service
remains tracked for cleanup even if startup inspection fails. Unknown identity
or incomplete cleanup holds the model slot closed. Names are fresh UUIDs and
are never intentionally reused; this is not a boundary against a privileged
administrator deliberately replacing an identically named validation service.

EOF, explicit release/abort, malformed protocol, process death, four seconds
without heartbeat, loss of fresh parked eligibility, or the 180-second absolute
limit revoke the lease. Deadlines are evaluated on manager ticks (normally at
most about one additional second; this is not a real-time guarantee).

A subsequent manager startup scans the fixed validation root even if opt-in was
removed. It kills/removes orphaned validation groups before model eligibility.
A scan/cleanup failure suppresses models, not manager or the vehicle interface.
No previous lease is resumed. A reboot removes transient units/kernel cgroups; stale socket
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

Future order: authorized deployment/opt-in;
next ordinary startup (no forced restart); verify normal Lightning/calibration/
READY/Park/parking brake/CD210 baseline; exercise harmless reservation/release,
crash, timeout, abort and session loss; verify native recovery each time. Only
then may separately authorized RDF/OP16 qualification proceed.

## Offline validation and limits

Focused tests exercise lease states, actual `ensure_running` logic with stand-in
processes, worker membership-before-exec, session EOF, orphan cleanup and tooling
failure handling. Model sources, compatibility profiles, selector, controls,
safety and submodule pointers are unchanged.

Mac tests cannot prove Linux SO_PEERCRED, real manager
scheduling, QCOM publications, or Lightning recognition preservation. Those are
explicit on-device reservation/release gates, not claims of this offline commit.
No RDF/OP16 inference or broad vehicle suites were run.

Cleanup replacement results: 34 focused tests PASS; independent review PASS.
On actual Comma: release, timeout-triggered cleanup and parent-crash each removed
five harmless parent/child/grandchild processes, including TERM-ignoring children
in new sessions. Cleanup took2.30–2.38s; an unrelated process survived and repeated
cleanup passed. These were backend-domain tests, not live model-slot tests.
SSH/session EOF and lease timeout routing passed offline; no physical SSH outage
or full180-second lease expiration was imposed on the device.

The old cgroup.kill hook never activated and created no legacy worker domains,
as established at the deployment checkpoint. This change therefore does not
claim migration cleanup of hypothetical legacy domains.

The live manager still ran dfd4b419 without the reservation hook at handoff.
Full live reservation/release plus native CD210 publication/vehicle recognition
verification remains blocked until a later authorized ordinary startup. No
manager restart, downloaded-model test or production-source deployment occurred.
