"""Health wire decoding and exact host-source provenance; no device required."""
import hashlib
import itertools
import json
from pathlib import Path
from types import SimpleNamespace

from panda import Panda


def test_separate_health_permission_bits():
  for ordinary, lateral, enabled in itertools.product((False, True), repeat=3):
    fields = list(Panda.HEALTH_STRUCT.unpack(bytes(Panda.HEALTH_STRUCT.size)))
    fields[8] = ((int(ordinary) * Panda.HEALTH_FLAG_CONTROLS_ALLOWED)
                 | (int(lateral) * Panda.HEALTH_FLAG_CONTROLS_ALLOWED_LATERAL)
                 | (int(enabled) * Panda.HEALTH_FLAG_MADS_SAFETY_ENABLED))
    packet = Panda.HEALTH_STRUCT.pack(*fields)
    device = object.__new__(Panda)
    device.health_version = Panda.HEALTH_PACKET_VERSION
    device._handle = SimpleNamespace(controlRead=lambda *args: packet, close=lambda: None)
    health = device.health()
    assert health["controls_allowed"] == ordinary
    assert health["controls_allowed_lateral"] == lateral
    assert health["mads_safety_enabled"] == enabled


def test_host_source_is_exact_pinned_upstream():
  root = Path(__file__).resolve().parents[3]
  manifest = json.loads((root / "openpilot/sunnypilot/UPSTREAM.json").read_text())
  assert manifest["commit"] == "e87dbbaba710bbfe7661d9ff064d46170cac9442"
  for relative, expected in manifest["git_blobs"].items():
    data = (root / relative).read_bytes()
    assert hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == expected
