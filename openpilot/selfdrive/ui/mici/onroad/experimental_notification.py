"""Short confirmation from published mode changes, never from a requested Param."""


class ExperimentalNotification:
  DURATION = 3.0

  def __init__(self):
    self.previous = None
    self.route = None
    self.expires = 0.0
    self.text = ''

  def update(self, now, mode, engaged, route, alert_present=False):
    if mode is None or route != self.route:
      self.previous, self.route, self.expires = mode, route, 0.0
      return ''
    if self.previous is not None and mode != self.previous:
      self.expires = now + self.DURATION
      self.text = self._text_for(mode, engaged)
    self.previous = mode
    if alert_present:
      # Do not replay a stale confirmation after a safety alert clears.
      self.expires = 0.0
    if mode and now < self.expires:
      self.text = self._text_for(mode, engaged)
    return self.text if now < self.expires else ''

  @staticmethod
  def _text_for(mode: bool, engaged: bool) -> str:
    # Same two-line "Title\nStatus" shape as the MADS notification and a
    # personality-change alert -- presentation only, same active/enabled/
    # disabled distinction as before.
    if not mode:
      return 'Experimental Mode\nDisabled'
    return 'Experimental Mode\nActive' if engaged else 'Experimental Mode\nEnabled'
