"""Headless tests of the actual border visibility method; no GL/messaging needed."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class TestExperimentalBorder(unittest.TestCase):
  def setUp(self):
    source = Path(__file__).parents[1] / 'mici/onroad/augmented_road_view.py'
    tree = ast.parse(source.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AugmentedRoadView')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_show_experimental_border')
    method.decorator_list = []
    namespace = {'UIStatus': SimpleNamespace(ENGAGED='engaged')}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    self.show = namespace['_show_experimental_border']
    self.sm = type('SubMasterStub', (dict,), {})()
    self.sm['selfdriveState'] = SimpleNamespace(enabled=True, experimentalMode=True)
    self.sm.valid = {'selfdriveState': True}
    self.sm.alive = {'selfdriveState': True}
    self.sm.recv_frame = {'selfdriveState': 12}

  def test_active_experimental(self):
    self.assertTrue(self.show(self.sm, 'engaged', 10, None))

  def test_chill_hidden(self):
    self.sm['selfdriveState'].experimentalMode = False
    self.assertFalse(self.show(self.sm, 'engaged', 10, None))

  def test_selected_but_disabled_hidden(self):
    self.sm['selfdriveState'].enabled = False
    self.assertFalse(self.show(self.sm, 'engaged', 10, None))

  def test_override_and_disengaged_hidden(self):
    for status in ['override', 'disengaged']:
      self.assertFalse(self.show(self.sm, status, 10, None))

  def test_alert_takes_precedence(self):
    self.assertFalse(self.show(self.sm, 'engaged', 10, object()))

  def test_stale_or_invalid_hidden(self):
    for name, value in [('valid', False), ('alive', False), ('recv_frame', 9)]:
      mapping = getattr(self.sm, name)
      original = mapping['selfdriveState']
      mapping['selfdriveState'] = value
      self.assertFalse(self.show(self.sm, 'engaged', 10, None))
      mapping['selfdriveState'] = original


if __name__ == '__main__':
  unittest.main()
