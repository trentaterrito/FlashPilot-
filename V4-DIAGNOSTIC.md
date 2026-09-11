# V4 onboarding diagnostic installer

V4 is the verified immutable v3 installer plus one explicitly authorized
recovery behavior: it writes the owner's existing ED25519 public key to setup
Params and enables SSH before publishing `continue.sh`. This prevents AGNOS from
removing setup access when FlashPilot enters onboarding, allowing read-only crash
evidence collection.

- Immutable source and local branch behavior: unchanged from v3
- AOL launcher: unchanged from v3
- Public-key fingerprint: `SHA256:9HPGApvkwkeyHYbObJ8E3+HGCz5vXYgfbrZ3qeu7WoU`
- Artifact: `flashpilot-dfd4b419-installer-v4-diagnostic`
- SHA-256: `91da2e8e5ed82a5fd29ab29616de7fc2abbe09be2f30a840e36e4b1549d2325f`
- Focused installer tests: pass
- Two consecutive builds: byte-identical

No private key, source modification, Panda/safety change, vehicle setting, or
road-test behavior is included.
