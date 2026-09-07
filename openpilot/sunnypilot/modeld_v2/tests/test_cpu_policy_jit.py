"""Local synthetic Tinygrad programs only; no published model pickle or weights."""
import io
import numpy as np
import pytest
from tinygrad import Tensor
from tinygrad.engine.jit import TinyJit
from openpilot.selfdrive.modeld.helpers import dump_oob, load_oob
from openpilot.sunnypilot.modeld_v2.compile_modeld import generate_queues_and_npy, make_run_policy, POLICY_INPUTS


def fake_policy(inputs):
  values = [inputs[k].flatten().sum().reshape(1, 1) for k in ('features_buffer','desire','traffic_convention','action_t')]
  if 'img' in inputs:
    values += [inputs[k].cast('float32').flatten().sum().reshape(1, 1) for k in ('img', 'big_img')]
  return {'output': Tensor.cat(*values, dim=1)}


def fake_vision(inputs):
  # Last warped frame's value is encoded as four features.
  return {'output': inputs['img'][:, -1:, :1, :1].reshape(1, 1).cast('float32').expand(1, 4)}


@pytest.mark.parametrize('supercombo', [True, False])
def test_captured_cpu_policy_roundtrip_preserves_live_inputs_and_queues(supercombo):
  shapes = {'img': (1, 12, 2, 2), 'big_img': (1, 12, 2, 2), 'features_buffer': (1, 3, 4),
            'desire': (1, 3, 8), 'traffic_convention': (1, 2), 'action_t': (1, 2)}
  queues, npy = generate_queues_and_npy(shapes, 1, 'CPU', is_supercombo=supercombo)
  fn = TinyJit(make_run_policy(None if supercombo else fake_vision, [fake_policy], slice(0,4), 1, shapes))
  history = []
  for step in range(1, 7):
    npy['desire'][:] = step
    npy['traffic_convention'][:] = step * 2
    npy['action_t'][:] = step * 3
    if supercombo:
      npy['prev_feat'][:] = step * 4
    warped = Tensor(np.full((2, 6, 2, 2), step, dtype=np.uint8), device='CPU').realize()
    outs = fn(warped=warped, **{k: queues[k] for k in POLICY_INPUTS})
    out = outs.numpy() if supercombo else outs[1].numpy()
    history = (history + [step])[-3:]
    expected = [sum(history) * (16 if supercombo else 4), sum(history)*8, step*4, step*6]
    if supercombo:
      expected += [sum((list(range(1, step+1)))[-2:])*24]*2
    np.testing.assert_array_equal(out, np.array([expected], dtype=np.float32))
    if step == 3:
      with io.BytesIO() as buf:
        dump_oob(fn, buf)
        buf.seek(0)
        fn = load_oob(buf)
