"""Lightning BSM presentation, independent of lane-change authorization."""

import pyray as rl


BSM_EDGE_WIDTH = 3
BSM_RED = (255, 38, 55)


def detected_sides(sm, started_frame: int) -> tuple[bool, bool]:
  """Only a fresh, current CarState's explicit detection may draw red."""
  if not (sm.valid['carState'] and sm.alive['carState'] and
          sm.recv_frame['carState'] >= started_frame):
    return False, False

  state = sm['carState']
  return state.leftBlindspotStatus == 'detected', state.rightBlindspotStatus == 'detected'


def draw_bsm_hue(rect: rl.Rectangle, left: bool, right: bool) -> None:
  """V1's low-alpha half-screen wash, below model, HUD, and alerts."""
  hue = rl.Color(*BSM_RED, 64)
  clear = rl.Color(*BSM_RED, 0)
  x, y, w, h = int(rect.x), int(rect.y), int(rect.width), int(rect.height)
  half = w // 2
  if left:
    rl.draw_rectangle_gradient_h(x, y, half, h, hue, clear)
  if right:
    rl.draw_rectangle_gradient_h(x + w - half, y, half, h, clear, hue)


def draw_bsm_edges(rect: rl.Rectangle, left: bool, right: bool) -> None:
  """V1's steady 3 px side edges, with no lane/path recoloring."""
  red = rl.Color(*BSM_RED, 255)
  x, y, w, h = int(rect.x), int(rect.y), int(rect.width), int(rect.height)
  if left:
    rl.draw_rectangle(x, y, BSM_EDGE_WIDTH, h, red)
  if right:
    rl.draw_rectangle(x + w - BSM_EDGE_WIDTH, y, BSM_EDGE_WIDTH, h, red)
