"""Distance-button gesture only; no control/engagement or safety permissions."""
import math

HOLD_SECONDS = 1.5
MAX_SAMPLE_AGE = 0.25


class DistanceButtonGesture:
  def __init__(self):
    self.pressed_at = None
    self.consumed = False
    self.wait_release = False
    self.last_update = None

  def update(self, now, edges, valid=True):
    """Return 'short', 'hold', or None. edges contains only distance-button booleans.

    After invalid/stale input, require a release before accepting another press.
    A hold is consumed once, including its eventual release; repeated press
    events cannot restart the timer. No elapsed frame-count assumptions.
    """
    interrupted = (not math.isfinite(now) or not valid or
                   (self.last_update is not None and not 0 <= now - self.last_update <= MAX_SAMPLE_AGE))
    self.last_update = now if math.isfinite(now) else None
    if interrupted:
      self.pressed_at, self.consumed, self.wait_release = None, False, True
      return None

    action = None
    for pressed in edges:
      if self.wait_release:
        if not pressed:
          self.wait_release = False
        continue
      if pressed:
        if self.pressed_at is None:
          self.pressed_at, self.consumed = now, False
      else:
        if self.pressed_at is not None and not self.consumed:
          action = 'hold' if now - self.pressed_at >= HOLD_SECONDS else 'short'
        self.pressed_at, self.consumed = None, False

    if self.pressed_at is not None and not self.consumed and now - self.pressed_at >= HOLD_SECONDS:
      self.consumed = True
      return 'hold'
    return action
