"""Observed checksum candidate, corruption coverage and explicit replay limits.

These are analysis tests, not an authorization implementation. Tests documenting
an accepted replay or uncovered corruption intentionally preserve the blocker.
"""
import json
from pathlib import Path
import random
import warnings

import numpy as np
import pytest

from opendbc.can.packer import CANPacker
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_ford_sunnypilot_mads import Harness
from tools.mads.analyze_ford_3cc import candidate_checksum, checksum_matches, decode, hypotheses

OBSERVED = json.loads((Path(__file__).parent / "data/ford_3cc_observed.json").read_text())
PAYLOADS = [bytes.fromhex(h) for h in OBSERVED["payloads"]]


def test_partial_container_warning_is_not_silently_reported_as_clean(monkeypatch):
  from tools.mads import analyze_ford_3cc as analyzer

  def partial_reader(*args, **kwargs):
    warnings.warn("Corrupted events detected", RuntimeWarning)
    return iter([None])

  monkeypatch.setattr(analyzer, "LogReader", partial_reader)
  result = analyzer.audit_container("local-fixture")
  assert result["error"] is None
  assert result["warnings"] == ["Corrupted events detected"]


def test_zero_checksum_false_rejects_on_complete_identified_corpus():
  assert sum(OBSERVED["payloads"].values()) == 377209
  assert len(PAYLOADS) == 631
  assert all(checksum_matches(p) for p in PAYLOADS)
  assert sum(n for h, n in OBSERVED["payloads"].items()
             if hypotheses(bytes.fromhex(h))["previous"] != bytes.fromhex(h)[5]) == 2795


def test_prior_mismatch_is_exactly_omitted_limit_term():
  for p in PAYLOADS:
    assert ((hypotheses(p)["previous"] - p[5]) & 255) == decode(p)["limit"]


def test_observed_group_has_independent_linear_evidence_for_all_four_terms():
  fields = [decode(p) for p in PAYLOADS]
  x = np.array([[d["state"], d["limit"], d["capability"], d["counter"], 1] for d in fields])
  y = np.array([255 - d["checksum"] for d in fields])
  weights, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
  assert rank == 5
  assert np.allclose(weights, [1, 1, 1, 1, 0], atol=1e-10)


@pytest.mark.parametrize("byte,bit", [(2, b) for b in range(3)] + [(4, b) for b in range(8)] + [(5, b) for b in range(8)])
def test_every_single_bit_error_in_covered_group_is_rejected(byte, bit):
  for p in PAYLOADS:
    bad = bytearray(p)
    bad[byte] ^= 1 << bit
    assert not checksum_matches(bad)


@pytest.mark.parametrize("length", [0, 1, 7, 9, 64])
def test_malformed_payload_not_checksum_valid(length):
  assert not checksum_matches(bytes(length))


def test_decode_matches_dbc_packer():
  packer, rng = CANPacker("ford_lincoln_base_pt"), random.Random(972)
  mapping = {"state": ("LatCtlSte_D_Stat", 7), "limit": ("LatCtlLim_D_Stat", 3),
             "capability": ("LatCtlCpblty_D_Stat", 3), "counter": ("LatCtlCpbltyDStat_No_Cnt", 15),
             "checksum": ("LatCtlCpbltyDStat_No_Cs", 255), "hands_off": ("LaHandsOff_B_Actl", 1),
             "denied": ("LaActDeny_B_Actl", 1), "available": ("LaActAvail_D_Actl", 3),
             "hands_confident": ("TjaHandsOnCnfdnc_B_Est", 1), "brake_enable": ("LsmcBrkDecelEnbl_D_Rq", 3)}
  for _ in range(100):
    values = {field: rng.randint(0, maximum) for _, (field, maximum) in mapping.items()}
    values["TrlrAn_An_TrgtCalc"] = rng.randint(-128, 127)
    values["LsmcBrk_Tq_Rq"] = rng.randint(0, 8191) * 4
    _, data, _ = packer.make_can_msg("Lane_Assist_Data3_FD1", 0, values)
    decoded = decode(data)
    assert all(decoded[name] == values[field] for name, (field, _) in mapping.items())
    assert decoded["trailer_angle"] == values["TrlrAn_An_TrgtCalc"]
    assert decoded["brake_torque"] == values["LsmcBrk_Tq_Rq"]


def test_checksum_is_not_full_frame_integrity_or_authentication():
  p = bytearray.fromhex("a80002809cf40000")
  p[0] ^= 0x80  # Hands-off varies in the logs, outside this empirical group.
  assert checksum_matches(p)
  p = bytearray.fromhex("a80002809cf40000")
  p[2] += 1  # state 2 -> 3
  p[4] -= 4  # counter 7 -> 6 cancels the changed state in the additive sum.
  assert checksum_matches(p)


def test_counter_plus_one_and_always_changing_hypotheses_are_falsified():
  # Acquisition-order examples, not injected frames: 129/2 and rdfv4/5.
  counters = [7, 15, 5, 13, 3, 11, 1, 9, 0, 7, 14, 5, 12]
  assert {(b - a) % 16 for a, b in zip(counters, counters[1:])} == {6, 7, 8}
  repeated_unavailable = bytes.fromhex("8800000000ff0000")
  assert decode(repeated_unavailable)["state"] == 0
  assert checksum_matches(repeated_unavailable)
  assert OBSERVED["payloads"][repeated_unavailable.hex()] == 6


def test_actual_gate_stale_missing_recovery_requires_new_tja():
  h = Harness()
  h.engage()
  h.omit_address = 0x3CC
  for _ in range(11):
    h.now += 10000
    h.safety.set_timer(h.now)
    h.refresh()
  assert not h.allowed()
  h.omit_address = None
  h.refresh()
  assert not h.allowed()
  h.engage()


def test_actual_gate_malformed_3cc_fails_closed():
  h = Harness()
  h.engage()
  h.safety.safety_rx_hook(libsafety_py.make_CANPacket(0x3CC, 0, b"\0" * 7))
  assert not h.allowed()


def test_current_gate_enforces_status_checksum():
  h = Harness()
  h.engage()
  bad = bytearray.fromhex("a80002809cf40000")
  bad[5] ^= 1
  assert not checksum_matches(bad)
  h.safety.safety_rx_hook(libsafety_py.make_CANPacket(0x3CC, 0, bad))
  assert not h.allowed()


def test_repeated_capture_cannot_renew_counter_progress():
  h = Harness()
  h.engage()
  captured = bytes.fromhex("a80002809cf40000")
  assert checksum_matches(captured)
  h.omit_address = 0x3CC
  h.safety.safety_rx_hook(libsafety_py.make_CANPacket(0x3CC, 0, captured))
  for i in range(30):
    h.now += 10000
    h.safety.set_timer(h.now)
    h.refresh()  # other required inputs remain fresh
    h.safety.safety_rx_hook(libsafety_py.make_CANPacket(0x3CC, 0, captured))
    assert h.allowed() == (i < 10)  # Existing 100 ms deadline; duplicates do not renew it.


def test_recorded_same_payload_can_recur_without_replay():
  # Actual 129/2 occurrences, 272 ms apart. Payload-only duplicate rejection
  # cannot distinguish this real recurrence from a replayed captured frame.
  p = bytes.fromhex("a80002809cf40000")
  assert 155884941823 - 155612709198 == 272232625
  assert checksum_matches(p)
  assert candidate_checksum(p) == 0xF4
