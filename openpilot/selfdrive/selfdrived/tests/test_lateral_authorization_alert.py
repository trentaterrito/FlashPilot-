from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.events import Events, ET


def test_lateral_control_unavailable_alert_renders_while_disabled():
  events = Events()
  events.add(log.OnroadEvent.EventName.lateralControlUnavailable)
  alerts = events.create_alerts([ET.PERMANENT])
  assert len(alerts) == 1
  alert = alerts[0]
  assert alert.alert_text_1 == "Lateral Control Unavailable"
  assert alert.alert_text_2 == "Steer Manually"
  assert alert.audible_alert == log.SelfdriveState.AudibleAlert.warningSoft


def test_new_panda_diagnostics_default_to_zero():
  panda_state = log.PandaState.new_message()
  assert panda_state.lateralRevocationReason == 0
  assert panda_state.lateralAuthorizationGates == 0
