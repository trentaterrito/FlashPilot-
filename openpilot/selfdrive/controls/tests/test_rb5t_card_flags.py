"""Execute the actual card gate block against a real Cap'n Proto builder."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from opendbc.car.structs import car
from opendbc.car.ford.values import CAR, FordFlags


@pytest.mark.parametrize("radar,shadow", [(False, False), (True, False), (True, True), (False, True)])
@pytest.mark.parametrize("lightning", [True, False])
def test_gate_accepts_capnp_flags_and_preserves_existing_bits(radar, shadow, lightning):
  source = Path(__file__).resolve().parents[2] / "car" / "card.py"
  tree = ast.parse(source.read_text())
  block = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
               and ast.unparse(node.test) == "self.params.get_bool('ExperimentalFordSteerAssistRadar')")
  cp = car.CarParams.new_message()
  cp.carFingerprint = CAR.FORD_F_150_LIGHTNING_MK1 if lightning else "OTHER"
  cp.flags = 1
  cp.radarUnavailable = True
  params = {"ExperimentalFordSteerAssistRadar": radar, "ExperimentalFordSteerAssistRadarShadow": shadow}
  instance = SimpleNamespace(CI=SimpleNamespace(CP=cp), params=SimpleNamespace(get_bool=params.__getitem__))
  exec(compile(ast.Module(body=[block], type_ignores=[]), str(source), "exec"), {"self": instance})
  expected = 1
  if lightning and radar:
    expected |= int(FordFlags.STEER_ASSIST_RADAR)
    if shadow:
      expected |= int(FordFlags.STEER_ASSIST_RADAR_SHADOW)
  assert cp.flags == expected
  assert cp.radarUnavailable == (not (lightning and radar))
  with car.CarParams.from_bytes(cp.to_bytes()) as decoded:
    assert decoded.flags == expected
