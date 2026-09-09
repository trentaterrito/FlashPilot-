"""No GPU imports: guardian pipe EOF unconditionally terminates the worker group."""
import os
import signal
import sys


def main():
  group, lease = map(int, sys.argv[1:])
  if group <= 1 or group == os.getpgrp():
    raise RuntimeError('invalid worker group')
  try:
    # Only the guardian owns the write end. No timeout/heartbeat spoof or child writer.
    while os.read(lease, 1):
      pass
  finally:
    os.close(lease)
    try:
      os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
      pass


if __name__ == '__main__':
  main()
