# FlashPilot installer v3 immutable-source validation

- Immutable target: `dfd4b419f73b2bccbfd0e4d7007124a68ae04c71`
- Installed local branch: `flashpilot-dev`
- Public repository: `https://github.com/trentaterrito/FlashPilot-.git`
- Artifact: `dist/flashpilot-dfd4b419-installer-v3`
- SHA-256: `5a8ad45c54359421e9375b64e2eab7f8be3a83f88e5b07808f4783745d71c41c`

The installer initializes an empty repository, fetches the exact target commit
object by full SHA, verifies `FETCH_HEAD`, and creates local `flashpilot-dev` at
that SHA. It never requires the mutable remote branch head to match.

Focused anonymous verification succeeded while remote `flashpilot-dev` was
`6b58c2b29a113936e702d9194640ec95ec49ed4e`: the immutable fetch returned
`dfd4b419`, local branch name was `flashpilot-dev`, and the exact commit tree
contained all six expected gitlinks. Installer tests pass the newer-remote-head
success case and fail closed for missing/wrong immutable commit, submodule pin or
recursive state mismatch, dirty state, LFS failure/pointer, local branch/SHA
mismatch, and partial activation.

Generated `/data/continue.sh` remains executable with exact AOL selector export,
and managed child inheritance of exact value `1` remains covered.
