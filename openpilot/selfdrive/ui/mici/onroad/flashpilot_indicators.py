"""FlashPilot presentation primitives; no Params, state writes, or control logic."""
import pyray as rl

from openpilot.cereal import log

BSM_EDGE_WIDTH = 2
BSM_GLOW_WIDTH = 12
BOLT_WIDTH = 48
BOLT_HEIGHT = 28
BOLT_GAP = 5
BOLT_BOTTOM_MARGIN = 8
BOLT_RELAXED = rl.Color(40, 214, 255, 255)
BOLT_STANDARD = rl.Color(255, 193, 64, 255)
BOLT_AGGRESSIVE = rl.Color(255, 82, 48, 255)
BOLT_INACTIVE = rl.Color(63, 68, 73, 255)

# Three rising, diagonal lightning shards, matching the supplied FlashPilot
# reference. The 48x28 box includes the halo; the 44x22 solid mark stays inset.
BOLT_SEGMENTS = (
  ((2, 25), (10.8, 22.8), (20.7, 7.4), (11.9, 8.5)),
  ((15.2, 21.7), (24, 19.5), (33.9, 5.2), (25.1, 6.3)),
  ((28.4, 18.4), (37.2, 16.2), (46, 3), (38.3, 4.1)),
)


def current_ui_message(sm, service, started_frame):
  return (sm.valid[service] and sm.alive[service] and sm.recv_frame[service] >= started_frame)


def bsm_display_state(sm, started_frame):
  if not current_ui_message(sm, 'carState', started_frame):
    return False, False
  cs = sm['carState']
  # Ford already publishes occupancy and per-side source freshness. Do not
  # substitute turn signals, desire, radar, or lane-change state for these.
  return bool(cs.leftBlindspot and cs.leftBlindspotValid), bool(cs.rightBlindspot and cs.rightBlindspotValid)


def personality_style(sm, started_frame):
  if not current_ui_message(sm, 'selfdriveState', started_frame):
    return BOLT_INACTIVE, 0
  return {
    log.LongitudinalPersonality.relaxed: (BOLT_RELAXED, 1),
    log.LongitudinalPersonality.standard: (BOLT_STANDARD, 2),
    log.LongitudinalPersonality.aggressive: (BOLT_AGGRESSIVE, 3),
  }.get(sm['selfdriveState'].personality, (BOLT_INACTIVE, 0))


def draw_bsm_edges(rect, left, right):
  """Steady outer lines with a narrow inward fade; no temporal state to latch."""
  red = rl.Color(255, 38, 55, 255)
  hue = rl.Color(255, 38, 55, 100)
  clear = rl.Color(255, 38, 55, 0)
  x, y, w, h = int(rect.x), int(rect.y), int(rect.width), int(rect.height)
  if left:
    rl.draw_rectangle_gradient_h(x, y, BSM_GLOW_WIDTH, h, hue, clear)
    rl.draw_rectangle(x, y, BSM_EDGE_WIDTH, h, red)
  if right:
    rl.draw_rectangle_gradient_h(x + w - BSM_GLOW_WIDTH, y, BSM_GLOW_WIDTH, h, clear, hue)
    rl.draw_rectangle(x + w - BSM_EDGE_WIDTH, y, BSM_EDGE_WIDTH, h, red)


def draw_personality_bolt(center_x, top, color, active_segments):
  x = center_x - BOLT_WIDTH / 2
  # Low-opacity expanded silhouettes give a steady halo without textures,
  # temporal animation. Inactive shards keep their solid, subdued silhouettes.
  for scale, opacity in ((1.2, 6), (1.12, 12), (1.05, 22), (1.0, 255)):
    for index, polygon in enumerate(BOLT_SEGMENTS):
      active = index < active_segments
      if scale != 1.0 and not active:
        continue
      tint = rl.color_alpha(color if active else BOLT_INACTIVE, opacity / 255)
      cx = sum(px for px, _ in polygon) / len(polygon)
      cy = sum(py for _, py in polygon) / len(polygon)
      points = [rl.Vector2(x + cx + (px - cx) * scale, top + cy + (py - cy) * scale) for px, py in polygon]
      for i in range(1, len(points) - 1):
        rl.draw_triangle(points[0], points[i], points[i + 1], tint)
