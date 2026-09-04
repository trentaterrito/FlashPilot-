from types import SimpleNamespace
import numpy as np
import pytest

from openpilot.selfdrive.ui.mici.onroad import model_renderer as ui


class Messages(dict):
  def __init__(self, lat=True, long=False, override=False):
    super().__init__(carControl=SimpleNamespace(latActive=lat, longActive=long),
                     carState=SimpleNamespace(steeringPressed=override))
    self.valid = dict.fromkeys(self, True)
    self.alive = dict.fromkeys(self, True)
    self.recv_frame = dict.fromkeys(self, 12)


@pytest.mark.parametrize('lat,long,override', [(True, False, False), (True, True, False),
                                             (False, False, False), (False, True, False), (True, False, True)])
def test_actual_control_states(lat, long, override):
  assert ui.ModelRenderer._control_display_state(Messages(lat, long, override), 10) == (lat, long, override)


@pytest.mark.parametrize('service', ['carControl', 'carState'])
@pytest.mark.parametrize('failure', ['valid', 'alive', 'recv_frame'])
def test_stale_invalid_or_previous_drive_cannot_show_active(service, failure):
  sm = Messages()
  getattr(sm, failure)[service] = 9 if failure == 'recv_frame' else False
  assert ui.ModelRenderer._control_display_state(sm, 10) == (False, False, False)


@pytest.mark.parametrize('override,expected', [(False, (0, 255, 64)), (True, (255, 255, 255))])
def test_lateral_only_boundaries_and_override(monkeypatch, override, expected):
  monkeypatch.setattr(ui, 'ui_state', SimpleNamespace(sm=Messages(override=override), started_frame=10))
  renderer = object.__new__(ui.ModelRenderer)
  renderer._torque_filter = SimpleNamespace(x=0)
  color = renderer._get_ll_color(1.0, True, True)
  assert (color.r, color.g, color.b) == expected


@pytest.mark.parametrize('experimental', [False, True])
def test_lateral_only_path_gray_even_in_experimental(monkeypatch, experimental):
  monkeypatch.setattr(ui, 'ui_state', SimpleNamespace(started_frame=10))
  calls = []
  monkeypatch.setattr(ui, 'draw_polygon', lambda *args, **kwargs: calls.append(kwargs))
  renderer = object.__new__(ui.ModelRenderer)
  renderer._rect = ui.rl.Rectangle(0, 0, 100, 100)
  renderer._path = SimpleNamespace(projected_points=np.array([[0, 0], [1, 1]]))
  renderer._experimental_mode = experimental
  renderer._draw_path(Messages())
  assert len(calls) == 1
  assert all(c.r == c.g == c.b for c in calls[0]['gradient'].colors)
  calls.clear()
  renderer._draw_path(Messages(lat=False))
  assert not calls


@pytest.mark.parametrize('experimental', [False, True])
def test_full_control_retains_existing_gradient(monkeypatch, experimental):
  monkeypatch.setattr(ui, 'ui_state', SimpleNamespace(started_frame=10, status=ui.UIStatus.ENGAGED))
  calls = []
  monkeypatch.setattr(ui, 'draw_polygon', lambda *args, **kwargs: calls.append(kwargs))
  renderer = object.__new__(ui.ModelRenderer)
  renderer._rect = ui.rl.Rectangle(0, 0, 100, 100)
  renderer._path = SimpleNamespace(projected_points=np.array([[0, 0], [1, 1]]))
  renderer._experimental_mode = experimental
  renderer._longitudinal_control = True
  renderer._blend_filter = SimpleNamespace(x=1.0, update=lambda value: None)
  renderer._exp_gradient = ui.Gradient(start=(0, 1), end=(0, 0), colors=ui.THROTTLE_COLORS, stops=[0, .5, 1])
  sm = Messages(long=True)
  sm['longitudinalPlan'] = SimpleNamespace(allowThrottle=True)
  renderer._draw_path(sm)
  colors = calls[0]['gradient'].colors
  assert [(c.r, c.g, c.b, c.a) for c in colors] == [(c.r, c.g, c.b, c.a) for c in ui.THROTTLE_COLORS]


def test_stale_control_does_not_draw_path(monkeypatch):
  monkeypatch.setattr(ui, 'ui_state', SimpleNamespace(started_frame=10))
  monkeypatch.setattr(ui, 'draw_polygon', lambda *args, **kwargs: pytest.fail('stale path drawn'))
  renderer = object.__new__(ui.ModelRenderer)
  renderer._path = SimpleNamespace(projected_points=np.array([[0, 0], [1, 1]]))
  sm = Messages()
  sm.alive['carControl'] = False
  renderer._draw_path(sm)
