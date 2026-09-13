from pathlib import Path
import os

import pytest

from tools.longitudinal_validation.diagnostics import CanFrame, FordDiagnosticDecoder, decode_ford_frame, motorola_unsigned


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
