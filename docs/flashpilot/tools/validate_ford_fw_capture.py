#!/usr/bin/env python3
"""
FlashPilot: pre-flight validator for newly-captured Ford ECU firmware, run BEFORE
proposing an edit to opendbc/car/ford/fingerprints.py.

This script adds NO new test inside opendbc itself. opendbc/car/ford/tests/test_ford.py
already validates every entry in FW_VERSIONS automatically and generically the moment it's
added (it's parameterized over FW_VERSIONS.items()) -- there is nothing for a new opendbc
test to check that it doesn't already check. What's actually missing is a way to run that
*same* validation logic against a captured-but-not-yet-committed firmware string, so a
transcription error or a mismatched ECU is caught before it ever touches fingerprints.py.

This script re-uses opendbc's own authoritative parsing/matching logic (imported directly,
never re-implemented) against whatever you just captured, and reports:
  - whether each string is well-formed per Ford's FW_PATTERN and the expected length/ECU
    part-number-prefix rules opendbc/car/ford/tests/test_ford.py already enforces
  - whether the parsed platform code matches an EXISTING F-150 Lightning entry (expected --
    same platform, new model year/part revision) or looks like a DIFFERENT platform's code
    (a red flag worth stopping on, not committing)
  - which of the four fingerprint-relevant ECUs (abs, eps, fwdRadar, fwdCamera) are present
    vs. missing, against opendbc's own PLATFORM_CODE_ECUS requirement

It never invents, guesses, or fills in a firmware value. It only validates what you hand it.

Requires opendbc's own runtime deps available on PYTHONPATH (numpy, pycapnp, pycryptodome --
whatever `cd opendbc_repo && ./setup.sh` installs) and the opendbc submodule initialized
(`git submodule update --init -- opendbc_repo`). Run from the FlashPilot repo root:

    PYTHONPATH=opendbc_repo python3 docs/flashpilot/tools/validate_ford_fw_capture.py \\
        path/to/captured_fw.json

Input file format (JSON): a mapping of ECU short name -> list of Python bytes-literal
strings, each written exactly as it would appear in fingerprints.py, e.g.:

    {
      "eps": ["b'RL38-14D003-AB\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00'"],
      "abs": ["b'RL38-2D053-BE\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00'"]
    }

See docs/flashpilot/FLASHLIGHTNING_FIRMWARE_CAPTURE.md for the capture procedure that
produces these strings, and exactly what to do with a captured set that passes.
"""
import ast
import json
import sys
from pathlib import Path

# ECU short-name (as used in the input JSON) -> canonical name, matching
# opendbc/car/ford/tests/test_ford.py's ECU_ADDRESSES / ECU_PART_NUMBER keys.
ECU_SHORT_NAMES = {
  "eps": "eps",
  "abs": "abs",
  "radar": "fwdRadar",
  "fwdradar": "fwdRadar",
  "camera": "fwdCamera",
  "fwdcamera": "fwdCamera",
}


def load_captured(path: Path) -> dict[str, list[bytes]]:
  raw = json.loads(path.read_text())
  out: dict[str, list[bytes]] = {}
  for ecu_key, literals in raw.items():
    ecu_name = ECU_SHORT_NAMES.get(ecu_key.strip().lower())
    if ecu_name is None:
      raise ValueError(f"Unknown ECU key {ecu_key!r} -- expected one of {sorted(set(ECU_SHORT_NAMES))}")
    parsed = []
    for lit in literals:
      value = ast.literal_eval(lit)
      if not isinstance(value, bytes):
        raise ValueError(f"Entry for {ecu_key!r} is not a bytes literal: {lit!r}")
      parsed.append(value)
    out[ecu_name] = parsed
  return out


def main(argv: list[str]) -> int:
  if len(argv) != 2:
    print(__doc__)
    return 2

  try:
    from opendbc.car.ford.values import CAR, FW_PATTERN, PLATFORM_CODE_ECUS, get_platform_codes
    from opendbc.car.ford.fingerprints import FW_VERSIONS
    from opendbc.car.structs import CarParams
  except ImportError as e:
    print(f"ERROR: could not import opendbc (is the submodule initialized and are its deps installed?): {e}")
    return 2

  Ecu = CarParams.Ecu
  ECU_NAME_TO_ENUM = {"abs": Ecu.abs, "eps": Ecu.eps, "fwdRadar": Ecu.fwdRadar, "fwdCamera": Ecu.fwdCamera}
  ECU_ADDR = {Ecu.abs: 0x760, Ecu.eps: 0x730, Ecu.fwdRadar: 0x764, Ecu.fwdCamera: 0x706}
  ECU_PART_NUMBER = {
    Ecu.eps: [b"14D003"],
    Ecu.abs: [b"2D053"],
    Ecu.fwdRadar: [b"14D049"],
    Ecu.fwdCamera: [b"14F397", b"14H102"],
  }

  captured = load_captured(Path(argv[1]))

  existing_lightning = FW_VERSIONS.get(CAR.FORD_F_150_LIGHTNING_MK1, {})
  existing_platform_codes: set[bytes] = set()
  for (ecu, addr, subaddr), fws in existing_lightning.items():
    for code, _year in get_platform_codes(fws):
      existing_platform_codes.add(code)

  ok = True
  print(f"Existing FORD_F_150_LIGHTNING_MK1 platform codes on file: {sorted(existing_platform_codes)}\n")

  for ecu_short, fws in captured.items():
    ecu = ECU_NAME_TO_ENUM[ecu_short]
    print(f"--- {ecu_short} (addr {hex(ECU_ADDR[ecu])}) ---")
    for fw in fws:
      problems = []
      if len(fw) != 24:
        problems.append(f"expected 24 bytes, got {len(fw)}")
      match = FW_PATTERN.match(fw)
      if match is None:
        problems.append("does not match Ford's FW_PATTERN (<MY hint><platform hint>-<part number>-<revision>)")
      else:
        part_number = match.group("part_number")
        if part_number not in ECU_PART_NUMBER[ecu]:
          problems.append(
            f"part number {part_number!r} not in expected set {ECU_PART_NUMBER[ecu]} for this ECU "
            f"-- wrong ECU, or a genuinely new part number opendbc hasn't seen for this slot")
      codes = get_platform_codes([fw]) if match else set()
      if len(codes) != 1:
        problems.append("could not parse exactly one platform code")
      elif next(iter(codes))[0] not in existing_platform_codes:
        # Not necessarily wrong -- but flag it loudly rather than silently accept
        problems.append(
          f"platform code {next(iter(codes))[0]!r} does NOT match any existing Lightning entry "
          f"{sorted(existing_platform_codes)} -- confirm this is really a Lightning ECU response, "
          f"not a different Ford model, before adding it")

      status = "OK" if not problems else "FLAGGED"
      ok = ok and not problems
      print(f"  {fw!r}")
      print(f"  -> {status}" + ("".join(f"\n     - {p}" for p in problems) if problems else ""))
    print()

  print("=== ECU coverage (opendbc's PLATFORM_CODE_ECUS requirement for fuzzy matching) ===")
  # Ecu enum members are plain ints (capnp-generated), not enum.Enum -- no .name attribute.
  # Go through our own short-name mapping instead of relying on one.
  ENUM_TO_NAME = {v: k for k, v in ECU_NAME_TO_ENUM.items()}
  required_names = sorted(ENUM_TO_NAME[e] for e in PLATFORM_CODE_ECUS)
  captured_names = sorted(captured.keys())
  missing = sorted(set(required_names) - set(captured_names))
  print(f"Required (exact+fuzzy fingerprinting): {required_names}")
  print(f"Captured this run:                     {captured_names}")
  if missing:
    print(f"MISSING for a full fuzzy-match candidate: {missing}")
    print("(Exact match against these specific strings can still work with a partial set; a fuzzy")
    print(" match on a firmware revision opendbc hasn't seen before needs all four.)")

  print()
  print("Overall:", "ALL ENTRIES OK" if ok else "ONE OR MORE ENTRIES FLAGGED -- do not commit without resolving")
  return 0 if ok else 1


if __name__ == "__main__":
  raise SystemExit(main(sys.argv))
