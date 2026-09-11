#!/usr/bin/env python3
"""Run a validation worker in a manager-owned slot lease.

stdin must receive heartbeats from the controlling SSH session, not from a
remote background loop. EOF or four seconds without input aborts.
"""
import argparse
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time


def enter(group, command):
  group = Path(group)
  if group != group.resolve(strict=True) or not str(group).startswith('/sys/fs/cgroup/'):
    raise ValueError('invalid worker cgroup')
  (group / 'cgroup.procs').write_text(str(os.getpid()))
  os.execvp(command[0], command)


def run(endpoint, command, session_fd=0):
  connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
  worker = group = None
  result = 1
  try:
    connection.settimeout(2)
    connection.connect(endpoint)
    connection.sendall(b'reserve\n')
    connection.setblocking(False)
    last_input = time.monotonic()
    buffer = b''
    while True:
      if time.monotonic() - last_input >= 4:
        raise RuntimeError('controlling session heartbeat expired')
      ready, _, _ = select.select([connection, session_fd], [], [], .2)
      if session_fd in ready:
        if not os.read(session_fd, 256):
          raise RuntimeError('controlling session closed')
        last_input = time.monotonic()
        connection.sendall(b'beat\n')
      if connection in ready:
        data = connection.recv(1024)
        if not data:
          raise RuntimeError('manager released/aborted slot')
        buffer += data
        if len(buffer) > 1024:
          raise RuntimeError('invalid manager response')
        if b'\n' in buffer:
          line, buffer = buffer.split(b'\n', 1)
          if group is not None or not line.startswith(b'reserved '):
            raise RuntimeError('unknown manager response')
          group = Path(line[len(b'reserved '):].decode())
          worker = subprocess.Popen([sys.executable, __file__, '--enter-cgroup', str(group), '--', *command],
                                    stdin=subprocess.DEVNULL, close_fds=True)
      if worker is not None and worker.poll() is not None:
        result = worker.returncode
        break
  finally:
    connection.close()
    if group is not None:
      try:
        (group / 'cgroup.kill').write_text('1')
      except FileNotFoundError:
        pass
      deadline = time.monotonic() + 10
      while group.exists() and time.monotonic() < deadline:
        time.sleep(.1)
      if worker is not None:
        worker.wait(timeout=2)
      if group.exists():
        raise RuntimeError('manager cleanup not confirmed; do not run another model')
  return result


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  mode = parser.add_mutually_exclusive_group(required=True)
  mode.add_argument('--endpoint')
  mode.add_argument('--enter-cgroup', help=argparse.SUPPRESS)
  parser.add_argument('command', nargs=argparse.REMAINDER)
  args = parser.parse_args()
  command = args.command[1:] if args.command[:1] == ['--'] else args.command
  if not command:
    parser.error('explicit worker command required')
  if args.enter_cgroup:
    enter(args.enter_cgroup, command)
    return
  def abort(signum, frame):
    raise RuntimeError('explicit/session signal abort')
  for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, abort)
  raise SystemExit(run(args.endpoint, command))


if __name__ == '__main__':
  main()
