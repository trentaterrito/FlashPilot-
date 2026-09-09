# Safe Harbor: artifact identity and native restoration

This is an **offline-prepared procedure**, not hardware qualification. No inference
or vehicle connection was used to develop it. Native CD210 source and model bytes
are unchanged. The existing parked checker and its guardian/watchdog are reused;
only identity binding and the transaction around it are new.

## Why the six RDF V2 chunks were wrong for this gate

Saved device digest `5574d0817a66ebda2037a1addf4c8fa348bfce357833c82c388b41a0052bc284`
and all six chunk hashes match the historical `recompiled19` RDF V2 package in
Sunnypilot catalog commit `b8a3835f19829c10961da0c88b527cbac5bd55b3` (August 13).
The September 1 `recompiled23` package has full digest
`52fcf48bfb991f327a8982037eb0855d9a63437d78e9f4828d2be54df0f32567` and three chunks.
Both use ref `35703097905a122c9f3ddf0d12889b4873d7e2a2` and the same basename.
The cached device catalog already names the new package. Refreshing that catalog
does not replace old files: the chunk reader follows the existing manifest.
A six-chunk manifest therefore keeps opening the complete old package. The exact
historic install/download sequence was not logged; this is not evidence that the
current downloader fetched six pieces from a three-piece catalog.

The previous selection cache could skip byte checks after validating the same
saved selection. Runner-type cache and the loader did not establish current
artifact identity. The candidate now checks current cached catalog identity,
manifest count, ordered chunk hashes and concatenated SHA before alternate launch.
The loader hashes into a private temporary file and deserializes those exact bytes.
Unbound `COMBINED_MODEL_PKL` overrides are rejected. Missing/malformed catalogs or
invalid selections fail back to the existing native-default selection policy.
No pickle is opened by preflight hashing.

## Recovery contract

The original checker cleaned up its worker but required the operator to restore
the original manager. That was insufficient after SSH loss. The new transaction:

1. Verifies the artifact **before stopping native operation**, pins original
   launchers/native model files, confirms native CD210 and fresh READY/Park/brake
   telemetry, and checks original service ownership of native modeld's cgroup.
2. Starts a systemd recovery service independent of SSH, with automatic restart
   after owner death. It acknowledges durable recovery state before any stop.
3. Stops the original `comma.service`, then starts its same foreground launcher in
   a temporary cgroup with `BLOCK=modeld,modeld_tinygrad`. The existing checker is
   the only allowlisted diagnostic job. Source, user model selection and the
   original service definition are never edited.
4. On success, failure, worker/lease-owner death, stdin/SSH EOF or deadline, stops
   the diagnostic cgroup and blocked-manager cgroup and verifies they are empty.
   Only then starts the unmodified original `comma.service`.
5. Requires native process/source identity, finite publications at 19–21 Hz over
   two seconds, fresh inputs and unchanged protected selections/Alpha Long before
   recording `restored`. A worker result and restoration result are separate;
   successful restoration does not mean inference passed.

A durable stop-intent precedes disruption. Restarting a dead recovery process
resumes restoration rather than restarting the diagnostic. Recovery itself does
not depend on the test artifact still existing. If recovery cannot verify the
native baseline, it retains the failure and retries; it never claims restoration.
The normal manager restart clears/recreates ordinary transient Params and
interrupts its managed producers. These are lifecycle effects, not manual setting
changes. Protected values are compared, never rewritten.

Assumptions: a functioning Linux systemd system manager, cgroup v2, readable process
identity, sufficient storage, and the recorded launchers behaving as verified.
The transaction refuses incompatible hosts before disruption. Mac tests exercise
real harmless process/descendant deaths and durable recovery logic; **Linux unit
launch, cgroup containment, the Comma launcher and real publication recovery still
require the first parked check**. Kernel/power/storage failure cannot be given an
absolute recovery guarantee by this tool.

## Prepare and run later, only under parked-validation approval

On the Mac, from the committed clean candidate (no network/model download):

```sh
python3 tools/model_validation/prepare_spec.py --catalog /absolute/current-catalog.json --output /absolute/new-stage
```

Transfer that pinned stage only when separately authorized. On the Comma, run
`configure_transaction.py` from the stage to capture the exact original baseline
and verify the installed artifact without inference or service changes:

```sh
source /etc/profile
python3 /absolute/stage/configure_transaction.py --stage /absolute/stage \
  --runtime /data/openpilot --model-root /absolute/model-cache --ref MODEL_REF \
  --output /absolute/new-result-directory --checker-sha256 PRINTED_SPEC_SHA256 \
  --write-spec /absolute/transaction.json
```

This prints the transaction-spec SHA. The stage must be readable but immutable
to the diagnostic process; the result parent must be writable by `comma`. The
transaction state directory is a separate fresh root-owned directory. With that
exact spec reviewed and the truck still READY/Park/parking brake applied:

```sh
sudo python3 /absolute/stage/transaction.py launch \
  --spec /absolute/transaction.json --spec-sha256 PRINTED_TRANSACTION_SHA256 \
  --state /data/model-validation-unique-state --authorize-parked-validation
```

Keep foreground SSH stdin open; EOF intentionally expires its lease. SSH loss
needs no remote cleanup command. After return/reconnect, inspect state.json:
`phase=restored`, `completed=true`, native health and protected-setting checks.
Inspect the separate checker RESULT.json for `passed=true`. Any other state is a
failed/incomplete gate. The systemd recovery unit and logs retain failure evidence.
Do not road-test based on artifact checks or local fault tests.

The saved six-chunk RDF V2 package remains ineligible. Obtain the catalog's exact
three-chunk package through the normal selector in a separately authorized future
step. These tools neither download nor silently substitute it.
