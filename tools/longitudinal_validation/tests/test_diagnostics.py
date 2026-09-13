from pathlib import Path
import os
import math

import pytest

from tools.longitudinal_validation.diagnostics import (CanFrame, DiagnosticUnavailable, FordDiagnosticDecoder,
                                                      decode_ford_frame, motorola_unsigned, require_diagnostics)


def _pack(signals, size=8):
  value = 0
  for start, length, raw in signals:
    position = start // 8 * 8 + 7 - start % 8
    shift = size * 8 - position - length
    value |= raw << shift
  return value.to_bytes(size, "big")


def test_motorola_boundaries_and_invalid_signal():
  data = _pack([(7, 10, 321), (39, 10, 1000)])
  assert motorola_unsigned(data, 7, 10, 0.1) == pytest.approx(32.1)
  assert motorola_unsigned(data, 39, 10, 0.1, -102.1) == pytest.approx(-2.1)
  with pytest.raises(ValueError):
    motorola_unsigned(b"\0", 7, 10)


def test_decode_complete_3d7_contract():
  data = _pack([(7, 10, 250), (9, 2, 3), (13, 4, 7), (23, 9, 260),
                (30, 7, 100), (39, 10, 991), (45, 9, 275)])
  out = decode_ford_frame(CanFrame(10, 0x3D7, data, 2))
  assert out["kind"] == "ford_object"
  assert out["d_rel"] == pytest.approx(25.0)
  assert out["confidence"] == 3 and out["object_class"] == 7
  assert out["native_ttc"] == pytest.approx(5.0)
  assert out["v_rel"] == pytest.approx(-3.0)
  assert out["v_lat"] == pytest.approx(0.5)
  assert out["y_rel"] == pytest.approx(2.0)


def test_health_aeb_acc_brake_bits_and_freshness():
  decoder = FordDiagnosticDecoder(fresh_ns=100)
  obj = _pack([(7, 10, 100), (9, 2, 2), (45, 9, 255)])
  health = _pack([(11, 1, 1), (22, 1, 1), (47, 1, 1)])
  aeb = _pack([(12, 13, 5000), (15, 1, 1), (55, 2, 2)])
  acc = _pack([(54, 1, 1), (55, 1, 1)])
  decoder.update([CanFrame(10, 0x3D7, obj, 2), CanFrame(20, 0x18A, health, 2),
                  CanFrame(30, 0x187, aeb, 2), CanFrame(35, 0x186, acc, 2)])
  snap = decoder.snapshot(40)
  assert snap["health"]["alignment_incomplete"] and snap["health"]["radar_blocked"]
  assert snap["health"]["fcw_visible"]
  assert "resume_display" not in snap["health"] and "stop_state" not in snap["health"]
  assert snap["aeb"]["brake_requested"] and snap["aeb"]["precharge_request"] == 2
  assert snap["acc"]["brake_precharge_requested"] and snap["acc"]["brake_decel_requested"]
  assert snap["offline_only"] and not snap["pass_fail_eligible"]
  assert not decoder.snapshot(200)["ford_object"]["fresh"]


def test_rb5t_never_claims_identity_and_stale_support_clears():
  decoder = FordDiagnosticDecoder(fresh_ns=100)
  obj = _pack([(7, 10, 200), (9, 2, 3), (45, 9, 255)])
  # One valid scan-2 point at 20 m and approximately zero azimuth.
  raw_az = round(3.1416 / 0.0003834)
  rb = _pack([(0, 1, 1), (17, 2, 2), (31, 14, 1280), (47, 14, raw_az)], size=64)
  decoder.update([CanFrame(10, 0x3D7, obj, 2), CanFrame(20, 0x120, rb, 1)])
  snap = decoder.snapshot(20)
  assert snap["rb5t"]["support_present"]
  assert snap["rb5t"]["association_semantics"] == "proximity_only_not_identity"
  decoder.update([CanFrame(21, 0x121, rb, 1)])
  assert decoder.snapshot(21)["rb5t"]["ambiguous"]
  assert not decoder.snapshot(200)["rb5t"]["support_present"]


def test_rb5t_empty_and_malformed_frames_clear_old_support():
  decoder = FordDiagnosticDecoder(fresh_ns=100)
  obj = _pack([(7, 10, 200), (9, 2, 3), (45, 9, 255)])
  raw_az = round(3.1416 / 0.0003834)
  rb = _pack([(0, 1, 1), (17, 2, 2), (31, 14, 1280), (47, 14, raw_az)], size=64)
  decoder.update([CanFrame(10, 0x3D7, obj, 2), CanFrame(20, 0x120, rb, 1)])
  assert decoder.snapshot(20)["rb5t"]["support_present"]

  # Preserve scan index while marking all slots invalid: this is an exact empty
  # scan contribution, and it must replace rather than refresh address 0x121.
  empty_scan = _pack([(17 + 72 * slot, 2, 2) for slot in range(6)], size=64)
  decoder.update([CanFrame(21, 0x121, empty_scan, 1)])
  snap = decoder.snapshot(21)
  assert snap["rb5t"]["available"] and snap["rb5t"]["fresh"]
  assert snap["rb5t"]["support_count"] == 1

  # Replacing the original address with an empty contribution clears support.
  decoder.update([CanFrame(22, 0x120, empty_scan, 1)])
  assert not decoder.snapshot(22)["rb5t"]["support_present"]

  decoder.update([CanFrame(23, 0x122, bytes(8), 1)])
  snap = decoder.snapshot(23)
  assert snap["rb5t"]["malformed"] and not snap["rb5t"]["available"]
  assert not snap["rb5t"]["fresh"] and not snap["rb5t"]["support_present"]


def test_signal_contract_matches_pinned_primary_dbc():
  # Independent source fixture: verify the literal contract against the pinned
  # sibling opendbc, rather than merely round-tripping this test module's packer.
  repo = Path(__file__).resolve().parents[3]
  dbc_root = Path(os.environ.get("LIGHTNING_VALIDATION_DBC_ROOT", str(repo / "opendbc_repo/opendbc/dbc")))
  if not (dbc_root / "ford_lincoln_base_pt.dbc").is_file():
    pytest.skip("Pinned opendbc DBCs unavailable: initialize exact submodule or set LIGHTNING_VALIDATION_DBC_ROOT")
  dbc = (dbc_root / "ford_lincoln_base_pt.dbc").read_text()
  for line in (
    "SG_ AccBrkPrchg_B_Rq : 54|1@0+ (1,0)",
    "SG_ AccBrkDecel_B_Rq : 55|1@0+ (1,0)",
    "SG_ CadsAlignIncplt_B_Actl : 11|1@0+ (1,0)",
    "SG_ CadsRadrBlck_B_Actl : 22|1@0+ (1,0)",
    "SG_ FcwVisblWarn_B_Rq : 47|1@0+ (1,0)",
  ):
    assert line in dbc

  rb_dbc = (dbc_root / "FORD_CADS_64.dbc").read_text()
  assert "BO_ 288 MRR_Detection_001: 64 MRR" in rb_dbc
  assert "BO_ 309 MRR_Detection_022: 24 MRR" in rb_dbc
  assert "SG_ CAN_DET_VALID_LEVEL_01_01 : 0|1@0+ (1,0)" in rb_dbc
  assert "SG_ CAN_SCAN_INDEX_2LSB_01_01 : 17|2@0+ (1,0)" in rb_dbc


def test_frame_validation():
  with pytest.raises(ValueError):
    CanFrame(-1, 1, b"", 0)
  with pytest.raises(TypeError):
    CanFrame(1, 1, bytearray(8), 0)
  for bus in (-1, 256, True, 1.5):
    with pytest.raises(ValueError):
      CanFrame(1, 1, b"", bus)


PRESERVED_135 = bytes.fromhex("808003000080088000808003000080088000000000000000")


@pytest.mark.parametrize("raw", [PRESERVED_135, bytes.fromhex("808000000080088000808000000080088000000000000000")])
def test_preserved_135_layout_degrades_without_guessing(raw):
  frame = CanFrame(12368721052122, 0x135, raw, 1)
  decoded = decode_ford_frame(frame)
  assert decoded["status"] == "UNAVAILABLE_UNSUPPORTED_LAYOUT"
  assert decoded["available"] is False and decoded["malformed"] is False
  assert decoded["detections"] is None and decoded["unavailable_slots"] == [3]
  error = decoded["error"]
  assert error["raw_hex"] == raw.hex() and error["size_bytes"] == 24
  assert (error["t_ns"], error["address"], error["bus"]) == (frame.t_ns, 0x135, 1)
  assert error["reason"] == "signal exceeds frame"
  assert error["layout_errors"] == [{"slot": 3, "signal": "azimuth", "dbc_start": 191,
    "length_bits": 14, "linear_start": 184, "linear_end_exclusive": 198,
    "available_bits": 192, "shift": -6, "predicate": "shift < 0"}]


def test_unsupported_layout_preflight_never_reads_payload(monkeypatch):
  from tools.longitudinal_validation import diagnostics
  def unexpected_read(*args, **kwargs):
    pytest.fail("unsupported layout must be rejected before signal extraction")
  monkeypatch.setattr(diagnostics, "motorola_unsigned", unexpected_read)
  assert decode_ford_frame(CanFrame(1, 0x135, PRESERVED_135, 1))["detections"] is None


def test_invalid_slot_payload_not_decoded(monkeypatch):
  from tools.longitudinal_validation import diagnostics
  original = diagnostics.motorola_unsigned
  calls = []
  def tracked(data, start, length, *args):
    calls.append(start)
    return original(data, start, length, *args)
  monkeypatch.setattr(diagnostics, "motorola_unsigned", tracked)
  decode_ford_frame(CanFrame(1, 0x120, bytes(64), 1))
  assert calls == [start for slot in range(6) for start in (slot * 72, slot * 72 + 17)]


@pytest.mark.parametrize("address", range(0x120, 0x135))
def test_valid_rb5t_values_identical_to_original_contract(address):
  raw_az = round(3.1416 / 0.0003834)
  raw = _pack([(72 * slot + offset, length, value) for slot in range(6)
               for offset, length, value in ((0, 1, 1), (17, 2, 2), (31, 14, 1280 + slot), (47, 14, raw_az))], size=64)
  expected = [{"scan": 2, "d_rel": math.cos(raw_az * .0003834 - 3.1416) * (1280 + slot) * .015625,
               "y_rel": -math.sin(raw_az * .0003834 - 3.1416) * (1280 + slot) * .015625} for slot in range(6)]
  assert decode_ford_frame(CanFrame(1, address, raw, 1)) == {
    "kind": "rb5t", "t_ns": 1, "available": True, "malformed": False, "detections": expected, "scan": 2}


def test_rb5t_unavailable_latches_no_stale_support_or_fake_no_target():
  decoder = FordDiagnosticDecoder()
  obj = _pack([(7, 10, 200), (9, 2, 3), (45, 9, 255)])
  rb = _pack([(0, 1, 1), (17, 2, 2), (31, 14, 1280), (47, 14, round(3.1416 / .0003834))], size=64)
  decoder.update([CanFrame(1, 0x3D7, obj, 2), CanFrame(2, 0x120, rb, 1)])
  assert decoder.snapshot()["rb5t"]["support_present"] is True
  decoder.update([CanFrame(3, 0x135, PRESERVED_135, 1), CanFrame(4, 0x120, rb, 1)])
  result = decoder.snapshot()
  assert decoder._rb5t_detections == [] and decoder._rb5t_by_address == {}
  assert result["rb5t"]["available"] is False and result["rb5t"]["fresh"] is False
  for name in ("support_count", "support_present", "ambiguous"):
    assert result["rb5t"][name] is None
  assert result["rb5t"]["first_unavailable_contribution"]["error"]["raw_hex"] == PRESERVED_135.hex()
  assert result["rb5t"]["unavailable_contribution_count"] == 1
  assert result["ford_object"]["fresh"] is True
  with pytest.raises(DiagnosticUnavailable, match="rb5t"):
    decoder.snapshot(required=("rb5t",))


def test_all_independent_diagnostics_and_freshness_unchanged_after_135():
  frames = [CanFrame(10, address, bytes(8), 2) for address in (0x3D7, 0x18A, 0x187, 0x186, 0x165)]
  reference, tested = FordDiagnosticDecoder(), FordDiagnosticDecoder()
  reference.update(frames)
  tested.update([CanFrame(9, 0x135, PRESERVED_135, 1), *frames])
  kinds = ("ford_object", "health", "aeb", "acc", "cruise")
  for now in (10, 300_000_010):
    a, b = reference.snapshot(now), tested.snapshot(now)
    assert {k: a[k] for k in kinds} == {k: b[k] for k in kinds}
  tested.snapshot(10, required=kinds)
  with pytest.raises(DiagnosticUnavailable, match="missing_or_stale"):
    tested.snapshot(300_000_010, required=kinds)


@pytest.mark.parametrize("address,kind", [(0x3D7, "ford_object"), (0x18A, "health"), (0x187, "aeb"),
                                          (0x186, "acc"), (0x165, "cruise")])
def test_malformed_independent_diagnostic_is_fatal_and_invalidates_prior(address, kind):
  decoder = FordDiagnosticDecoder()
  decoder.update([CanFrame(1, address, bytes(8), 2)])
  with pytest.raises(DiagnosticUnavailable, match="required independent diagnostic malformed"):
    decoder.update([CanFrame(2, address, bytes(7), 2)])
  assert decoder.snapshot()[kind]["available"] is False
  assert decoder.snapshot()[kind]["fresh"] is False
  assert decoder.snapshot()[kind]["error"]["raw_hex"] == "00" * 7
  with pytest.raises(DiagnosticUnavailable):
    decoder.snapshot(required=(kind,))


def test_required_unknown_and_missing_diagnostics_fail_closed():
  for name in ("rb5t", "ford_object", "unrecognized"):
    with pytest.raises(DiagnosticUnavailable):
      require_diagnostics(FordDiagnosticDecoder().snapshot(), [name])


def test_unrelated_decoder_exception_is_not_swallowed(monkeypatch):
  from tools.longitudinal_validation import diagnostics
  def broken(frame):
    raise RuntimeError("unrelated decoder bug")
  monkeypatch.setattr(diagnostics, "decode_ford_frame", broken)
  with pytest.raises(RuntimeError, match="unrelated decoder bug"):
    FordDiagnosticDecoder().update([CanFrame(1, 0x135, PRESERVED_135, 1)])
