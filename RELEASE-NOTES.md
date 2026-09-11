Minimal Comma four AArch64 ELF installer for the preserved FlashPilot source.

Target repository: https://github.com/trentaterrito/FlashPilot-.git
Branch: flashpilot-dev
Required HEAD: dfd4b419f73b2bccbfd0e4d7007124a68ae04c71
opendbc: 42fa6447ed0ff9a0497a14ca136ea45d923c1106
panda: 8bcae70c896bf3aee98b28641755f82b4aa5bf8b

Installer SHA256: 28561e559600d6891cde687af935f88a135f602bc6a71ca68db3365083427191

Requires normal uninstall/reset followed by Custom Software setup. Refuses an existing /data/openpilot or continue.sh. Does not erase a live checkout or preserve erased StarPilot. Clones fresh into a unique staging directory, checks exact branch/SHA and all six pins, initializes recursive submodules, fetches/verifies LFS, checks clean source, then publishes the standard continue.sh launcher last. Never installs packages, modifies the managed runtime, patches source, restores settings, or launches FlashPilot manually.

Clone/check failures leave no active launcher. Ordinary post-rename validation failures move the candidate back out of the active path. Staged activation is not power-loss transactional. After handoff, AGNOS/runtime/build are owned by normal comma.service/comma.sh startup; bootstrap failure does not automatically restore StarPilot. Keep the independently verified Mac backup.

The log is /data/flashpilot-install-dfd4b419f73b2bccbfd0e4d7007124a68ae04c71.log. CHECKOUT PASS is not runtime success: manager/UI/modeld and managed startup must be independently checked after installation. No vehicle test or on-device execution was performed for this release.

Source is attached as installer-source.tar.gz, with install.sh, entry.S, deterministic build.py, and test_installer.py. Build uses clang's AArch64 assembler and a minimal static ELF container. Non-device verification covers 20 simulated shell success/failure scenarios, static ELF and embedded-source checks, and reproducible binary hash. This is a custom wrapper, not a comma-issued installer.

Anonymous clone/submodules PASS; all 240 LFS objects (886 MB) downloaded and materialized, object integrity PASS, exact branch/HEAD/six pins and clean source PASS. The pinned repository stores four documentation PNGs as ordinary blobs under an LFS pattern; object-only fsck validates LFS content without changing those original Git blobs.
