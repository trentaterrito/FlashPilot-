"""Monitoring-only engagement latch. Cannot authorize steering or longitudinal."""


class MadsMonitoring:
  def __init__(self):
    self.engaged = False

  def update(self, *, fresh, requested, authorized):
    # Loss of host data must not relax monitoring while steering might still be
    # active. Fresh negative intent AND authorization are needed to clear it.
    if fresh:
      self.engaged = bool(requested or authorized)
    return self.engaged
