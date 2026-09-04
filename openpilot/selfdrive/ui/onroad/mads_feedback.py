"""Read-only driver feedback. No Params, control requests or permission writes."""
from dataclasses import dataclass


@dataclass(frozen=True)
class MadsDisplay:
  visible: bool = False
  title: str = ""
  detail: str = ""
  warning: str = ""
  active: bool = False  # fully-gated lateral-active (includes panda authorization)
  # Raw signals for consumers that render their own presentation (e.g. the
  # transient mode-change notification) rather than this module's own status
  # box. Read-only mirrors of already-computed state -- no new semantics.
  feature: bool = False
  requested: bool = False
  panda_authorized: bool = False
  long_active: bool = False


class MadsFeedback:
  def __init__(self):
    self.seen = False
    self.was_active = False
    self.button = None
    self.warning = ""
    self.warning_until = 0.
    self.wait_since = None

  def update(self, *, now, onroad, lightning, fresh, feature, requested, authorized,
             host_authorized, eligible, lat_active, long_active, tja):
    if not onroad or not lightning:
      self.__init__()
      return MadsDisplay()
    self.seen = self.seen or (fresh and feature)
    if not self.seen:
      return MadsDisplay()
    active = bool(fresh and feature and requested and authorized and host_authorized and lat_active)
    rising = fresh and self.button is False and tja
    if fresh:
      self.button = tja
    else:
      self.button = None
    if self.was_active and not active:
      self.warning = "Steering released - steer manually"
      self.warning_until = now + 3.
    elif rising and (not eligible or not feature):
      self.warning = "Lateral unavailable - check state or faults"
      self.warning_until = now + 3.
    if fresh and feature and requested and not active:
      self.wait_since = now if self.wait_since is None else self.wait_since
      if now - self.wait_since >= 1. and self.warning_until < now and self.warning != "Lateral not authorized - steer manually":
        self.warning = "Lateral not authorized - steer manually"
        self.warning_until = now + 3.
    else:
      self.wait_since = None
    self.was_active = active
    if active:
      self.warning_until = 0.
      self.warning = ""
    elif not requested and now >= self.warning_until:
      self.warning = ""
    warning = self.warning if now < self.warning_until else ""
    if not fresh:
      return MadsDisplay(True, "MADS STATE STALE", "Steer manually | LAT/LONG unknown", warning, False,
                        feature=feature, requested=requested, panda_authorized=authorized, long_active=long_active)
    if not feature:
      if not warning:
        self.seen = False
        return MadsDisplay()
      return MadsDisplay(True, "MADS OFF", "Steer manually", warning, False,
                        feature=False, requested=requested, panda_authorized=authorized, long_active=long_active)
    state = "ACTIVE" if active else "REQUESTED" if requested else "NOT REQUESTED"
    long_state = "ON" if long_active else "OFF"
    detail = f"REQ {'ON' if requested else 'OFF'} | PANDA {'YES' if authorized else 'NO'}"
    return MadsDisplay(True, f"MADS ON | LAT {state} | LONG {long_state}", detail, warning, active,
                        feature=feature, requested=requested, panda_authorized=authorized, long_active=long_active)


def update_feedback(feedback, sm, cp, onroad, now):
  sources = ("controlsState", "pandaStates", "carControl", "carState")
  fresh = sm.all_checks(list(sources)) and all(0 <= now * 1e9 - sm.logMonoTime[s] <= 100_000_000 for s in sources)
  lightning = cp is not None and cp.carFingerprint == "FORD_F_150_LIGHTNING_MK1"
  pandas = sm["pandaStates"]
  matched = (lightning and len(pandas) == 1 and str(pandas[0].safetyModel) == "ford"
             and len(cp.safetyConfigs) == 1 and pandas[0].safetyParam == cp.safetyConfigs[0].safetyParam)
  cs, cc = sm["controlsState"], sm["carControl"]
  return feedback.update(now=now, onroad=onroad, lightning=lightning, fresh=bool(fresh and matched),
                         feature=bool(matched and pandas[0].madsSafetyEnabled),
                         requested=cs.madsState.enabled, authorized=bool(matched and pandas[0].controlsAllowedLateral),
                         host_authorized=cs.madsAuthorized, eligible=cs.madsEligible,
                         lat_active=cc.latActive, long_active=cc.longActive, tja=sm["carState"].genericToggle)


def draw_mads_status(display, rect, font):
  if not display.visible:
    return
  import pyray as rl
  width = min(rect.width - 24, 900)
  font_size = min(30., max(12., rect.width / 45.))
  lines = (display.title, display.detail)
  measured = max(rl.measure_text_ex(font, line, font_size, 0).x for line in lines)
  if measured > width - 16:
    font_size *= (width - 16) / measured
  height = 2.6 * font_size
  x, y = rect.x + (rect.width - width) / 2, rect.y + rect.height - height - 18
  color = rl.Color(128, 216, 166, 255) if display.active else rl.Color(255, 200, 110, 255)
  rl.draw_rectangle_rec(rl.Rectangle(x, y, width, height), rl.Color(0, 0, 0, 210))
  for index, line in enumerate(lines):
    text_width = rl.measure_text_ex(font, line, font_size, 0).x
    rl.draw_text_ex(font, line, rl.Vector2(x + (width - text_width) / 2, y + index * font_size * 1.2), font_size, 0, color)
