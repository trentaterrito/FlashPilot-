"""Short, transient confirmation of MADS lateral/longitudinal state changes.

Presentation-only, in the same spirit as experimental_notification.py: this
module has no opinion on MADS engagement semantics and does not read/write
any Param or panda state itself. It only watches the already-computed,
read-only MadsDisplay (see mads_feedback.py) for meaningful transitions and
emits text for ModeNotificationView -- the same large top-banner presentation
used for the Experimental Mode confirmation.

Never claims lateral is active unless panda has actually authorized it:
"active" here is MadsDisplay.active, which mads_feedback.py already computes
as fully gated (feature on AND requested AND panda-authorized AND host
lateral-active).
"""


class MadsNotification:
  DURATION = 3.0

  def __init__(self):
    self.previous = None  # (requested, lateral_active, long_active) or None
    self.route = None
    self.expires = 0.0
    self.text = ''

  def update(self, now, display, route, alert_present=False):
    if not display.feature:
      # Selector off entirely: no notification surface for users who never
      # opted in to MADS.
      self.previous, self.route, self.expires = None, route, 0.0
      return ''

    lateral_active = bool(display.panda_authorized and display.active)
    state = (bool(display.requested), lateral_active, bool(display.long_active))

    if route != self.route:
      self.previous, self.route, self.expires = state, route, 0.0
      return ''

    if self.previous is not None and state != self.previous:
      requested, active, long_active = state
      if not requested:
        self.text = 'MADS\nDisabled'
        self.expires = now + self.DURATION
      elif active and long_active:
        self.text = 'MADS\nLateral + Longitudinal'
        self.expires = now + self.DURATION
      elif active:
        self.text = 'MADS\nLateral Only'
        self.expires = now + self.DURATION
      else:
        # Requested but not yet authorized/active: nothing has actually taken
        # effect yet, so no confirmation banner -- avoid claiming a mode the
        # vehicle hasn't actually entered.
        self.expires = 0.0

    self.previous = state

    if alert_present:
      # Do not replay a stale confirmation after a safety alert clears.
      self.expires = 0.0

    return self.text if now < self.expires else ''
