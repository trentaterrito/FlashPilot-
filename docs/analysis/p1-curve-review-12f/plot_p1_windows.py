#!/usr/bin/env python3
"""Plot recorded P1 busy and negative-control curve windows."""

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

from analyze_p1_windows import read_segment


def plot_window(axs, rows, lo, hi, title):
  w = [r for r in rows if lo <= r["t"] <= hi]
  t = np.array([r["t"] - lo for r in w])
  axs[0].plot(t, [r["model_curvature"] * 1000 for r in w], label="model desired curvature")
  axs[0].plot(t, [r["desired_curvature"] * 1000 for r in w], label="controls desired curvature", alpha=.8)
  axs[0].set_ylabel("curvature (1/km)")
  axs[0].set_title(title)
  axs[1].plot(t, [r["path_angle"] * 180 / np.pi for r in w], label="CAN path-angle command")
  axs[1].plot(t, [r["wheel"] for r in w], label="measured steering wheel", alpha=.8)
  axs[1].set_ylabel("angle (deg)")
  axs[2].plot(t, [r["v"] * 2.2369362921 for r in w], label="vehicle speed")
  axs[2].set_ylabel("mph")
  axs[2].set_xlabel("window seconds")
  for ax in axs:
    ax.grid(alpha=.25)
    ax.legend(loc="best", fontsize=8)


def main(paths):
  by_seg = {}
  for path in map(Path, paths):
    rows, _, _, _ = read_segment(path)
    if rows:
      by_seg[rows[0]["seg"]] = rows
  selections = [
    (26, 2.5, 12.5, "Negative control: segment 26, 2.5–12.5 s"),
    (26, 17.5, 27.5, "Busy curve/bookmark window: segment 26, 17.5–27.5 s"),
    (27, 35.0, 45.0, "Curve transition/bookmark window: segment 27, 35–45 s"),
    (28, 22.5, 32.5, "Calmer curve control: segment 28, 22.5–32.5 s"),
  ]
  for seg, lo, hi, title in selections:
    fig, axs = plt.subplots(3, 1, figsize=(11, 8), sharex=True, constrained_layout=True)
    plot_window(axs, by_seg[seg], lo, hi, title)
    fig.savefig(Path(__file__).parent / f"segment_{seg}_{str(lo).replace('.', 'p')}_{str(hi).replace('.', 'p')}.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
  main(sys.argv[1:])
