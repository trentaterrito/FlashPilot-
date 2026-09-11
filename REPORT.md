# FlashPilot installer: published URL and artifact verified

Source: src/install.sh, src/entry.S, src/build.py. Tests: tests/test_installer.py.
Build: python3 src/build.py, using clang AArch64 integrated assembler, then a deterministic ELF header around a relocation-free text section. No libc, linked dependencies, persistent service, feature logic, telemetry, or updater is embedded. The wrapper execs the installed /bin/bash with the embedded bootstrap script.

Artifact: dist/flashpilot-dfd4b419-installer
SHA256: 28561e559600d6891cde687af935f88a135f602bc6a71ca68db3365083427191
Public installation URL: https://github.com/trentaterrito/FlashPilot-/releases/download/installer-dfd4b419-v1/flashpilot-dfd4b419-installer
Anonymous download matches the final artifact byte-for-byte. Published source archive also matches locally. This verifies delivery, not device startup.

Exact target: https://github.com/trentaterrito/FlashPilot-.git, flashpilot-dev, dfd4b419f73b2bccbfd0e4d7007124a68ae04c71. All six top-level submodule pins are verified, including opendbc 42fa6447ed0ff9a0497a14ca136ea45d923c1106 and panda 8bcae70c896bf3aee98b28641755f82b4aa5bf8b. Every recursive submodule must match its gitlink and be clean. LFS is fetched using managed git-lfs; no package installation.

Existing StarPilot: normal uninstall/reset must remove it before custom setup. The shim refuses an existing /data/openpilot or continue.sh; it neither deletes a live installation nor copies its files. Separately stored backups are not read or modified. The Mac backup is untouched.

Clone/check failure: no active checkout or launcher is created. A staging directory and log remain for diagnosis. Before launcher publication, ordinary validation failures after the staging rename move the complete candidate back out of /data/openpilot. The directory rename and final continue.sh rename are staged activation, not a transaction guaranteed across sudden power loss. An interrupted activation may require inspection/cleanup through normal setup before retry.

Bootstrap failure: once continue.sh is published, the normal comma.service -> comma.sh -> launch_openpilot.sh path owns AGNOS/runtime/build and startup. The shim logs BOOTSTRAP PENDING and never claims manager/UI/modeld success. It does not install a persistent rollback monitor or automatically restore erased StarPilot. The verified Mac FlashPilot archive remains the recovery source. Hardware startup verification must be done separately after a later authorized install; the present task stops before contacting the Comma.

Validation: Bash syntax and 20 mocked success/failure scenarios pass; ELF header, machine type, entry instruction, no object relocations, embedded script, and deterministic rebuild verified. Fresh anonymous Mac clone confirms exact branch HEAD and all six gitlinks. All 240 LFS assets downloaded/materialized and object integrity passed; main and submodule trees clean. Four ordinary documentation PNG blobs in the pinned source match an LFS pattern; fsck --objects validates LFS objects without rejecting unchanged ordinary blobs. AArch64 execution, managed startup and device process health are not tested.

Resolved access prerequisite: user explicitly authorized making all three required repositories public. Visibility changes verified. Installer and exact build source published as release installer-dfd4b419-v1 targeting preserved dfd4b419. Anonymous downloads checked byte-for-byte. Production branch remains at dfd4b419. No Comma connection, settings changes, runtime modifications or backup writes.
