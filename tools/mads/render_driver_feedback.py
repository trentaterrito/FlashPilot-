"""Render the actual status-label function in a hidden preview window; no vehicle."""
import argparse
import pyray as rl
from openpilot.selfdrive.ui.onroad.mads_feedback import MadsDisplay, draw_mads_status


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("output")
  args = parser.parse_args()
  rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  rl.init_window(1280, 720, "FlashPilot MADS feedback preview")
  target = rl.load_render_texture(1280, 720)
  rl.begin_texture_mode(target)
  rl.clear_background(rl.Color(35, 40, 45, 255))
  for i, state in enumerate((
    MadsDisplay(True, "MADS ON | LAT ACTIVE | LONG OFF", "REQ ON | PANDA YES", "", True),
    MadsDisplay(True, "MADS ON | LAT REQUESTED | LONG OFF", "REQ ON | PANDA NO"),
    MadsDisplay(True, "MADS STATE STALE", "Steer manually | LAT/LONG unknown"),
    MadsDisplay(True, "MADS ON | LAT NOT REQUESTED | LONG ON", "REQ OFF | PANDA NO"),
  )):
    rect = rl.Rectangle((i % 2) * 640, (i // 2) * 360, 640, 360)
    rl.draw_text("MADS feedback preview", int(rect.x + 20), int(rect.y + 20), 22, rl.WHITE)
    draw_mads_status(state, rect, rl.get_font_default())
  rl.end_texture_mode()
  screenshot = rl.load_image_from_texture(target.texture)
  rl.image_flip_vertical(screenshot)
  rl.export_image(screenshot, args.output)
  rl.unload_image(screenshot)
  rl.unload_render_texture(target)
  rl.close_window()


if __name__ == "__main__":
  main()
