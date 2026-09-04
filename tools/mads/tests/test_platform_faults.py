"""Compile and exercise the actual board predicate; no mock of its logic."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def native(tmp_path_factory):
  output = tmp_path_factory.mktemp("mads_platform") / "platform.so"
  mode = "-dynamiclib" if sys.platform == "darwin" else "-shared"
  subprocess.run([shutil.which("cc"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", mode, "-fPIC",
                  "-I", str(ROOT / "panda"), str(Path(__file__).with_name("platform_harness.c")), "-o", str(output)], check=True)
  lib = ctypes.CDLL(str(output))
  lib.platform_ready.restype = ctypes.c_bool
  lib.platform_fault.argtypes = [ctypes.c_int, ctypes.c_int]
  return lib


@pytest.fixture
def board(native):
  native.platform_reset()
  return native


def test_healthy_predicate_is_not_permission_grant(board):
  assert board.platform_ready()


@pytest.mark.parametrize("kind,bus", [(k, 0) for k in (0, 1, 2, 3, 4, 6, 7)] + [(k, b) for k in (11, 12, 15) for b in range(3)])
def test_each_platform_fault_vetoes(board, kind, bus):
  board.platform_fault(kind, bus)
  assert not board.platform_ready()
  if kind == 15:
    # Counter deltas are observations. Caller latches the veto until a fresh
    # heartbeat AND needs a new physical TJA selection (covered by Ford tests).
    assert board.platform_ready()
  else:
    assert not board.platform_ready()


def test_adc_lock_never_reads_ignition_gpio(board):
  board.platform_fault(5, 0)
  assert board.platform_ready()
  assert board.platform_gpio_reads() == 0


@pytest.mark.parametrize("kind,bus", [(k, 0) for k in (8, 9, 10)] + [(k, b) for k in (13, 14, 16, 17) for b in range(3)])
def test_diagnostic_counter_alone_is_not_steering_fault(board, kind, bus):
  board.platform_fault(kind, bus)
  assert board.platform_ready()
