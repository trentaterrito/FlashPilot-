#!/usr/bin/env python3
"""One-model parked check using the existing guardian; never arranges vehicle state.

Preparation only until explicitly authorized. This temporarily supplies NORMAL
model publications in a vacant model-process slot; it is not a shadow test.
No service, BLOCK, Param or installed source changes are performed by this tool.
"""
import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from guardian_support import digest, read_state, safe_state, launch_guarded, finish_guarded
from process_support import Metrics, await_start, install_parent_guard, check_finite

TOPICS = ('modelV2', 'drivingModelData', 'cameraOdometry')
MODEL_PROCESSES = ('modeld', 'modeld_tinygrad')
BLOCK_REQUIRED = frozenset(MODEL_PROCESSES)
OVERLAYS = ('openpilot.sunnypilot.models.artifact',
            'openpilot.sunnypilot.models.helpers',
            'openpilot.sunnypilot.livedelay.helpers',
            'openpilot.sunnypilot.modeld_v2.camera_offset_helper',
            'openpilot.sunnypilot.modeld_v2.modeld')
SUBSCRIPTIONS = ('deviceState', 'carState', 'narrowRoadCameraState', 'extrinsicsCalibration',
                 'driverMonitoringState', 'carControl', 'lateralDelay')


def worker_environment(ambient, runtime, output):
  # Allow only OS/session essentials. No inherited model/backend/compiler flags.
  env = {k: ambient[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ', 'TMPDIR') if k in ambient}
  env.update(PYTHONPATH=str(runtime), PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE='0',
             DEV='QCOM', CACHEDB=str(Path(output)/'tinygrad-cache.db'))
  return env


def assert_profile(actual, bundle):
  overrides = {entry['key']: entry['value'] for entry in bundle.get('overrides', [])}
  expected = {'generation':bundle.get('generation', 0), 'is20hz':bool(bundle.get('is20hz', False)),
              'lat':float(overrides.get('lat', 0)), 'long':float(overrides.get('long', 0))}
  if any(actual[k] != value for k, value in expected.items()):
    raise RuntimeError(f'Loaded profile mismatch: expected {expected}, got {actual}')
  if actual['expected_hz'] != 20:
    raise RuntimeError('This gate requires the current runner 20 Hz execution contract')
  return expected


def read_trace(path, final=False):
  data = Path(path).read_bytes()
  if not final and not data.endswith(b'\n'):
    data = data.rsplit(b'\n', 1)[0] if b'\n' in data else b''
  return [json.loads(line) for line in data.splitlines()]


def read_spec(path, expected):
  if not re.fullmatch('[0-9a-f]{64}',expected) or digest(path) != expected:
    raise ValueError('Prepared spec hash mismatch')
  return json.loads(Path(path).read_text())


def one_bundle(catalog, ref):
  bundles = [b for b in catalog['bundles'] if b['ref'] == ref]
  if len(bundles) != 1:
    raise ValueError('Requested ref must identify exactly one catalog bundle')
  bundle = bundles[0]
  if bundle['runner'] != 'tinygrad' or bundle.get('is_big', False):
    raise ValueError('Only retained QCOM alternate-runner bundles are supported')
  if len(bundle['models']) != 1:
    raise ValueError('Expected one combined artifact; inspect this exact bundle')
  artifact = bundle['models'][0]['artifact']
  name = artifact['file_name']
  if not name or Path(name).name != name or name in ('.', '..'):
    raise ValueError('Unsafe artifact filename')
  if not re.fullmatch('[0-9a-f]{64}', artifact['download_uri']['sha256']):
    raise ValueError('A full expected artifact SHA-256 is required')
  return bundle, artifact


@contextlib.contextmanager
def verified_snapshot(open_artifact, path, expected, directory):
  """Hash and parse the SAME bytes; do not re-open a mutable model cache."""
  with tempfile.TemporaryFile(dir=directory) as raw:
    hasher = hashlib.sha256()
    with open_artifact(str(path)) as source:
      while chunk := source.read(1024 * 1024):
        hasher.update(chunk)
        raw.write(chunk)
    actual = hasher.hexdigest()
    if actual != expected:
      raise ValueError(f'Artifact hash mismatch: expected {expected}, got {actual}')
    raw.seek(0)
    # The existing loader needs peek(); the file is private and deleted on close.
    import io
    with io.BufferedReader(raw) as snapshot:
      yield snapshot


def json_metadata(value):
  if isinstance(value, slice):
    return {'slice': [value.start, value.stop, value.step]}
  if isinstance(value, dict):
    return {str(k): json_metadata(v) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [json_metadata(v) for v in value]
  if value is None or isinstance(value, (str, int, float, bool)):
    return value
  raise ValueError(f'Unsupported metadata value {type(value).__name__}')


def output_contract(value):
  if isinstance(value, (tuple, list)):
    return {'type': type(value).__name__, 'items': [output_contract(v) for v in value]}
  if not hasattr(value, 'numpy'):
    raise TypeError(f'Unsupported policy return {type(value).__name__}')
  array = value.numpy()
  import numpy as np
  if not np.isfinite(array).all():
    raise ValueError('Nonfinite raw model output')
  return {'type': 'tensor', 'shape': list(array.shape), 'dtype': str(array.dtype), 'finite': True}


def slot_vacant(manager_data, extra_pids=()):
  state = {p['name']: p['running'] for p in manager_data}
  return (all(name in state and not state[name] for name in BLOCK_REQUIRED) and not extra_pids)


def competing_models(exclude=()):
  """Report matching PIDs only; never expose unrelated process arguments."""
  found = []
  for proc in Path('/proc').glob('[0-9]*'):
    pid = int(proc.name)
    if pid in exclude:
      continue
    try:
      words = (proc/'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace').split()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
      continue
    if any(w.endswith('/modeld') or w in ('./modeld', 'modeld', 'modeld_tinygrad',
               'selfdrive.modeld.modeld_tinygrad', 'openpilot.selfdrive.modeld.modeld',
               'openpilot.sunnypilot.modeld_v2.modeld') for w in words):
      found.append(pid)
  return sorted(found)


def verify_source(spec, source, runtime):
  def git(*args):
    return subprocess.check_output(['git', '-C', str(runtime), *args], text=True).strip()
  if git('rev-parse', 'HEAD') != spec['runtime_baseline'] or git('status', '--porcelain'):
    raise RuntimeError('Installed baseline drift; reconcile before this check')
  for relative, expected in spec['pins'].items():
    if subprocess.check_output(['git', '-C', str(runtime/relative), 'rev-parse', 'HEAD'], text=True).strip() != expected:
      raise RuntimeError('Submodule drift: '+relative)
  for relative, expected in spec['source_files'].items():
    if digest(source/relative) != expected:
      raise RuntimeError('Frozen overlay mismatch: '+relative)
  here = Path(__file__).resolve().parent
  for relative, expected in spec['tool_files'].items():
    if digest(here/relative) != expected:
      raise RuntimeError('Prepared tool changed: '+relative)


def load_overlay(name, source):
  parent_name, leaf = name.rsplit('.', 1)
  parent = importlib.import_module(parent_name)
  spec = importlib.util.spec_from_file_location(name, source/(name.replace('.', '/')+'.py'))
  module = importlib.util.module_from_spec(spec)
  sys.modules[name] = module
  spec.loader.exec_module(module)
  setattr(parent, leaf, module)
  return module


def worker(args):
  install_parent_guard(args.parent_pid)
  await_start(args.start_fd)
  metrics = Metrics(Path(args.output)/'trace.jsonl')
  try:
    spec = read_spec(args.spec,args.spec_sha256)
    verify_source(spec, Path(args.source), Path(args.runtime))
    raw_bundle, artifact = one_bundle(spec['catalog'], args.ref)
    if os.environ.get('COMBINED_MODEL_PKL'):
      raise RuntimeError('COMBINED_MODEL_PKL override is forbidden')
    from openpilot.common.hardware import COMMA_HARDWARE
    if not COMMA_HARDWARE or sys.platform != 'linux':
      raise RuntimeError('Actual Comma/QCOM required')
    from openpilot.cereal import messaging
    from openpilot.common import file_chunker
    from openpilot.common.hardware.hw import Paths
    from openpilot.sunnypilot.models.fetcher import ModelParser
    from openpilot.sunnypilot.modeld_v2 import meta_helper
    parsed = ModelParser.parse_models({'bundles': [raw_bundle]})
    if len(parsed) != 1:
      raise RuntimeError('Current selector rejects requested bundle')
    bundle = parsed[0]
    source = Path(args.source)
    for name in OVERLAYS:
      md = load_overlay(name, source)
    if md.chestnut_present():
      raise RuntimeError('This check is for QCOM only')
    # One immutable diagnostic choice drives BOTH artifact loading and profile.
    # No persistent choice or runner cache is written.
    md.get_verified_active_bundle = lambda **kwargs: bundle
    meta_helper.get_active_bundle = lambda *a, **kw: bundle
    Paths.model_root = staticmethod(lambda: args.model_root)
    # Adapted from the existing native probe: observe the actual worker clients.
    real_submaster = md.SubMaster
    class TraceSubMaster(real_submaster):
      def __init__(self, services, **kwargs):
        if tuple(services) != SUBSCRIPTIONS:
          raise RuntimeError('Unexpected model subscriptions')
        super().__init__(services, **kwargs)
        self.check_counts = dict.fromkeys(SUBSCRIPTIONS, 0)
        self.check_updates = 0
      def update(self, *a, **kw):
        result = super().update(*a, **kw)
        self.check_updates += 1
        for key in SUBSCRIPTIONS:
          self.check_counts[key] += int(self.updated[key])
        if self.check_updates == 1 or self.check_updates % 20 == 0:
          now = time.monotonic_ns()
          values = {key:{'updates':self.check_counts[key], 'log_mono_ns':int(self.logMonoTime[key]),
                         'seen':bool(self.seen[key]), 'valid':bool(self.valid[key]),
                         'alive':bool(self.alive[key]), 'age':(now-self.logMonoTime[key])/1e9}
                    for key in SUBSCRIPTIONS}
          physical = {'lateral_delay':float(self['lateralDelay'].lateralDelay),
                      'calibration_rpy':list(self['extrinsicsCalibration'].rpyCalib)}
          check_finite(physical)
          metrics.emit('subscriptions', inputs=values, **physical)
        return result
    md.SubMaster = TraceSubMaster
    real_vipc = md.VisionIpcClient
    required_streams = {md.VisionStreamType.VISION_STREAM_NARROW_ROAD, md.VisionStreamType.VISION_STREAM_WIDE_ROAD}
    class TraceVisionClient:
      @staticmethod
      def available_streams(server, *a, **kw):
        if server != 'camerad':
          raise RuntimeError('Unexpected camera server')
        streams = real_vipc.available_streams(server, *a, **kw)
        if streams and not required_streams.issubset(set(streams)):
          raise RuntimeError('Both real road-camera streams required')
        return streams
      def __init__(self, server, stream, conflate):
        if server != 'camerad' or stream not in required_streams:
          raise RuntimeError('Unexpected camera connection')
        self.actual = real_vipc(server, stream, conflate)
        self.stream, self.frames = str(stream), 0
      def __getattr__(self, name):
        return getattr(self.actual, name)
      def connect(self, *a, **kw):
        connected = self.actual.connect(*a, **kw)
        if connected:
          metrics.emit('camera_connected', stream=self.stream, width=self.actual.width, height=self.actual.height)
        return connected
      def recv(self, *a, **kw):
        frame = self.actual.recv(*a, **kw)
        if frame is not None:
          self.frames += 1
          if self.frames == 1 or self.frames % 20 == 0:
            metrics.emit('camera_frame', stream=self.stream, received=self.frames,
                         frame_id=int(self.actual.frame_id), timestamp_sof_ns=int(self.actual.timestamp_sof))
        return frame
    md.VisionIpcClient = TraceVisionClient
    selected_path = Path(args.model_root)/artifact['file_name']
    real_load = md._load_jits
    def traced_load(path, selected_artifact):
      if Path(path).resolve() != selected_path.resolve() or selected_artifact.to_dict() != bundle.models[0].artifact.to_dict():
        raise RuntimeError('Requested model resolved to a different artifact')
      # Production loader verifies chunks and full digest into a private snapshot.
      loaded = real_load(path, selected_artifact)
      metrics.emit('artifact_loaded', requested_ref=args.ref, requested_name=bundle.internalName,
                   path=str(selected_path), sha256=artifact['download_uri']['sha256'],
                   metadata=json_metadata(loaded['metadata']), profile=bundle.to_dict())
      return loaded
    md._load_jits = traced_load
    original_init, original_run = md.ModelState.__init__, md.ModelState.run
    def traced_init(self, *a, **kw):
      original_init(self, *a, **kw)
      profile = {'generation':self.generation, 'is20hz':bool(bundle.is20hz),
                 'lat':self.LAT_SMOOTH_SECONDS, 'long':self.LONG_SMOOTH_SECONDS,
                 'expected_hz':self.constants.MODEL_FREQ}
      assert_profile(profile, bundle.to_dict())
      real_policy = self.run_policy
      self.check_count = 0
      def policy(*a, **kw):
        start = time.monotonic_ns()
        output = real_policy(*a, **kw)
        contract = output_contract(output)
        self.check_count += 1
        metrics.emit('inference', count=self.check_count, output=contract,
                     elapsed_ns=time.monotonic_ns()-start)
        return output
      self.run_policy = policy
      self.check_runs = 0
      metrics.emit('runner_initialized', generation=self.generation, is20hz=bool(bundle.is20hz),
                   model_type=self._combined_model_type, lat=self.LAT_SMOOTH_SECONDS,
                   long=self.LONG_SMOOTH_SECONDS, expected_hz=self.constants.MODEL_FREQ,
                   inputs={k:list(v.shape) for k,v in self.input_queues.items()})
    def traced_run(self, bufs, transforms, inputs, prepare_only):
      self.check_runs += 1
      if self.check_runs == 1 or self.check_runs % 20 == 0:
        transform_state = {key:{'finite':bool(md.np.isfinite(value).all()),
                                'nonzero':bool(md.np.any(value)), 'shape':list(value.shape)}
                           for key,value in transforms.items()}
        if not all(value['finite'] for value in transform_state.values()):
          raise ValueError('Nonfinite consumed camera transform')
        metrics.emit('consumed_run', transforms=transform_state,
                     input_shapes={k:list(v.shape) for k,v in inputs.items()},
                     action_t=inputs['action_t'].tolist() if 'action_t' in inputs else None,
                     prepare_only=bool(prepare_only))
      output = original_run(self, bufs, transforms, inputs, prepare_only)
      if output is not None:
        for name, array in output.items():
          if not md.np.isfinite(array).all():
            raise ValueError('Nonfinite parsed output '+name)
        metrics.emit('parsed', shapes={k:list(v.shape) for k,v in output.items()})
      return output
    md.ModelState.__init__, md.ModelState.run = traced_init, traced_run
    real_pub = md.PubMaster
    class TracePub:
      def __init__(self, topics):
        if tuple(topics) != TOPICS:
          raise RuntimeError('Unexpected publication set')
        self.actual = real_pub(topics)
        self.counts = dict.fromkeys(TOPICS, 0)
      def send(self, topic, message):
        check_finite(message.to_dict())
        self.actual.send(topic, message)
        self.counts[topic] += 1
        metrics.emit('publication', topic=topic, count=self.counts[topic],
                     message_mono_ns=int(message.logMonoTime), valid=bool(message.valid), finite=True)
    md.PubMaster = TracePub
    metrics.emit('worker_started', requested_ref=args.ref, normal_publications=True)
    md.main()
    raise RuntimeError('Runner returned unexpectedly')
  except BaseException as error:
    metrics.emit('failure', exception=type(error).__name__, reason=str(error))
    raise


def series(rows, key='mono_ns'):
  times = [r[key] for r in rows]
  if len(times) < 2 or any(b <= a for a,b in zip(times,times[1:])):
    return {'count':len(times), 'hz':None, 'monotonic':False}
  return {'count':len(times), 'hz':(len(times)-1)*1e9/(times[-1]-times[0]),
          'max_gap_seconds':max(b-a for a,b in zip(times,times[1:]))/1e9, 'monotonic':True}


def summarize(rows, since_ns=0):
  steady = [r for r in rows if r['mono_ns'] >= since_ns]
  loaded = [r for r in rows if r['event']=='artifact_loaded']
  inferences = [r for r in steady if r['event']=='inference']
  publications = {t:[r for r in steady if r['event']=='publication' and r['topic']==t] for t in TOPICS}
  camera_rows = [r for r in steady if r['event']=='camera_frame']
  cameras = {stream:[r for r in camera_rows if r['stream']==stream] for stream in {r['stream'] for r in camera_rows}}
  return {'artifact_loaded':loaded[-1] if loaded else None,
          'runner_initializations':[r for r in rows if r['event']=='runner_initialized'],
          'inference_reached':bool(inferences), 'inference':series(inferences),
          'output_contract':inferences[-1]['output'] if inferences else None,
          'publications':{t:{**series(rs,'message_mono_ns'), 'all_valid':bool(rs) and all(r['valid'] for r in rs),
                             'all_finite':bool(rs) and all(r['finite'] for r in rs)} for t,rs in publications.items()},
          'worker_pids':sorted({r['pid'] for r in rows}),
          'consumed_subscriptions':[r for r in steady if r['event']=='subscriptions'],
          'consumed_runs':[r for r in steady if r['event']=='consumed_run'],
          'cameras':{stream:{'samples':len(rs), 'first':rs[0], 'last':rs[-1],
                            'advancing':all(b['frame_id']>a['frame_id'] and b['timestamp_sof_ns']>a['timestamp_sof_ns']
                                            for a,b in zip(rs,rs[1:]))} for stream,rs in cameras.items()},
          'failures':[r for r in rows if r['event']=='failure']}


def assert_consumed_inputs(summary):
  cameras = summary['cameras']
  if len(cameras) != 2 or any(v['samples'] < 2 or not v['advancing'] for v in cameras.values()):
    raise RuntimeError('Both actual camera streams must advance during the scored interval')
  subscriptions, runs = summary['consumed_subscriptions'], summary['consumed_runs']
  if len(subscriptions) < 2 or len(runs) < 2:
    raise RuntimeError('Actual consumed-input evidence incomplete')
  for key in ('extrinsicsCalibration', 'lateralDelay', 'narrowRoadCameraState'):
    if subscriptions[-1]['inputs'][key]['updates'] <= subscriptions[0]['inputs'][key]['updates']:
      raise RuntimeError('Consumed input did not update: '+key)
    for row in subscriptions:
      value = row['inputs'][key]
      if not (value['seen'] and value['valid'] and value['alive'] and 0 <= value['age'] < .5):
        raise RuntimeError('Consumed input unhealthy: '+key)
  if any(len(row['transforms']) != 2 or not all(v['finite'] and v['nonzero'] for v in row['transforms'].values()) for row in runs):
    raise RuntimeError('Actual calibrated camera transforms missing or invalid')


def run(args):
  if not args.authorize_production_publishers:
    raise RuntimeError('Separate approval and --authorize-production-publishers required')
  if sys.platform != 'linux' or sys.flags.optimize:
    raise RuntimeError('Non-optimized Comma/Linux Python required')
  if not 5 <= args.seconds <= 60:
    raise ValueError('Steady interval must be 5–60 seconds')
  spec = read_spec(args.spec,args.spec_sha256)
  if args.ref in spec.get('known_contract_failures', {}):
    raise RuntimeError('Known offline contract failure: '+spec['known_contract_failures'][args.ref])
  verify_source(spec, Path(args.source), Path(args.runtime))
  raw_bundle, artifact = one_bundle(spec['catalog'], args.ref)
  if os.environ.get('COMBINED_MODEL_PKL'):
    raise RuntimeError('Remove diagnostic model-path override before running')
  identity = load_overlay('openpilot.sunnypilot.models.artifact', Path(args.source))
  from openpilot.sunnypilot.models.fetcher import ModelParser
  selected = ModelParser.parse_models({'bundles': [raw_bundle]})[0]
  identity.verify_artifact(args.model_root, selected.models[0].artifact)
  from openpilot.cereal import messaging
  from openpilot.common.params import Params
  params = Params()
  sm = messaging.SubMaster(['carState','pandaStates','deviceState','managerState',
                            'extrinsicsCalibration','lateralDelay',*TOPICS])
  def eligible(exclude=()):
    state = read_state(sm, params)
    manager_age = (time.monotonic_ns()-sm.logMonoTime['managerState'])*1e-9
    if not safe_state(state,'parked') or not (sm.valid['managerState'] and sm.alive['managerState'] and 0 <= manager_age < 2):
      raise RuntimeError('Fresh READY/Park/brake/no-permission/manager guard failed')
    if not slot_vacant([p.to_dict() for p in sm['managerState'].processes], competing_models(exclude)):
      raise RuntimeError('Model process slot is not reserved; operator must arrange it separately')
    return state
  until = time.monotonic()+4
  while time.monotonic() < until:
    sm.update(100)
  before = eligible()
  output = Path(args.output)
  output.mkdir(parents=True,exist_ok=False)
  result = {'transaction_id':args.transaction_id,'requested_ref':args.ref,'requested_name':raw_bundle['short_name'],
            'expected_sha256':artifact['download_uri']['sha256'], 'passed':False,
            'before':before,'normal_publications':True,'transaction_restore_required':True,
            'candidate':spec['candidate'],'runtime_baseline':spec['runtime_baseline'],
            'runner_alive_at_end':False,'restart_count':0,'spec_sha256':args.spec_sha256}
  protected = ('ModelManager_ActiveBundle','ModelManager_ActiveBundleChestnut','ModelRunnerTypeCache',
               'AlphaLongitudinalEnabled','ChestnutLoading','ChestnutActive')
  def snapshot():
    return {k:digest(Path('/data/params/d')/k) if (Path('/data/params/d')/k).is_file() else None for k in protected}
  saved = snapshot()
  p = watch = lease = None
  steady = None
  def abort(signum, frame):
    raise RuntimeError('guardian signal '+str(signum))
  signal.signal(signal.SIGTERM,abort)
  signal.signal(signal.SIGINT,abort)
  env = worker_environment(os.environ,args.runtime,output)
  result['worker_environment_keys'] = sorted(env)
  try:
    with (output/'runner.log').open('x') as log:
      argv = [sys.executable,'-u',str(Path(__file__).resolve()),'worker','--parent-pid',str(os.getpid()),
              '--spec',args.spec,'--spec-sha256',args.spec_sha256,'--ref',args.ref,'--source',args.source,'--runtime',args.runtime,
              '--model-root',args.model_root,'--output',str(output)]
      p,watch,lease = launch_guarded(argv,cwd=output,env=env,stdout=log)
      result['worker_pid'] = p.pid
      deadline = time.monotonic()+180
      received = {t:[] for t in TOPICS}
      while True:
        sm.update(50)
        eligible((p.pid,))
        if watch.poll() is not None or p.poll() is not None:
          raise RuntimeError('Worker/watchdog exited; inspect runner.log and trace.jsonl')
        now = time.monotonic_ns()
        healthy = True
        for topic in (*TOPICS,'extrinsicsCalibration','lateralDelay'):
          age = (now-sm.logMonoTime[topic])*1e-9
          healthy &= bool(sm.valid[topic] and sm.alive[topic] and 0 <= age < .5)
        for topic in TOPICS:
          if sm.updated[topic]:
            check_finite(sm[topic].to_dict())
            if steady is not None:
              received[topic].append({'mono_ns':int(sm.logMonoTime[topic])})
        if steady is None and healthy:
          steady = now
        elif steady is not None and not healthy:
          raise RuntimeError('Steady publication or calibration/delay health lost')
        if steady is not None and (now-steady)/1e9 >= args.seconds:
          break
        if time.monotonic() > deadline:
          raise TimeoutError('Startup/steady interval deadline')
      rows = read_trace(output/'trace.jsonl')
      summary = summarize(rows,steady)
      result.update(summary)
      result['received'] = {t:series(rs) for t,rs in received.items()}
      result['runner_alive_at_end'] = p.poll() is None
      if not summary['artifact_loaded'] or not summary['inference_reached'] or summary['failures'] or summary['worker_pids'] != [p.pid]:
        raise RuntimeError('Artifact/inference/stability evidence incomplete')
      if len(summary['runner_initializations']) != 1:
        raise RuntimeError('Exactly one initialized runner required')
      assert_profile(summary['runner_initializations'][0],summary['artifact_loaded']['profile'])
      assert_consumed_inputs(summary)
      measured = [summary['inference'],*summary['publications'].values()]
      if any(not x['monotonic'] or not 19 <= x['hz'] <= 21 or x['max_gap_seconds'] > .5 for x in measured):
        raise RuntimeError('Observed inference/publication cadence failed')
      if any(not x['all_valid'] or not x['all_finite'] for x in summary['publications'].values()):
        raise RuntimeError('Invalid/nonfinite publications')
      if any(x['count'] < 2 for x in result['received'].values()):
        raise RuntimeError('Required publications not received')
      for topic in TOPICS:
        sent_times = {r['message_mono_ns'] for r in rows if r['event']=='publication' and r['topic']==topic}
        if any(r['mono_ns'] not in sent_times for r in received[topic]):
          raise RuntimeError('Received publication is not attributable to the sole probe: '+topic)
      result['received_publications_bound_to_worker'] = True
      result['passed'] = True
  except BaseException as error:
    result['failure'] = str(error)
    raise
  finally:
    if p is not None:
      result['runner_alive_at_end'] = p.poll() is None
      result['unexpected_worker_exit_code'] = p.poll()
      result['restart_count'] = 0  # This guardian never restarts a failed worker.
      try:
        finish_guarded(p,watch,lease)
      except BaseException as error:
        result['passed'] = False
        result['cleanup_failure'] = str(error)
      result['worker_stopped'] = p.poll() is not None
      result['worker_exit_code_after_cleanup'] = p.returncode
    try:
      result['protected_params_unchanged'] = snapshot()==saved
    except OSError as error:
      result['protected_params_unchanged'] = False
      result['param_check_failure'] = str(error)
    if not result['protected_params_unchanged']:
      result['passed'] = False
    if (output/'trace.jsonl').exists():
      try:
        result['trace_summary'] = summarize(read_trace(output/'trace.jsonl',final=True))
        if result['trace_summary']['failures']:
          result['passed'] = False
      except (ValueError, KeyError) as error:
        result['passed'] = False
        result['trace_failure'] = str(error)
    (output/'RESULT.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,allow_nan=False))


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  sub = parser.add_subparsers(dest='command',required=True)
  for name in ('run','worker'):
    p = sub.add_parser(name)
    for flag in ('spec','spec-sha256','ref','source','runtime','model-root','output'):
      p.add_argument('--'+flag,required=True)
    if name == 'run':
      p.add_argument('--transaction-id',required=True)
      p.add_argument('--seconds',type=int,default=15)
      p.add_argument('--authorize-production-publishers',action='store_true')
    else:
      p.add_argument('--parent-pid',type=int,required=True)
      p.add_argument('--start-fd',type=int,required=True)
  args = parser.parse_args()
  for name in ('spec','source','runtime','model_root','output'):
    setattr(args,name,str(Path(getattr(args,name)).expanduser().resolve()))
  if args.command == 'worker':
    worker(args)
  else:
    run(args)


if __name__ == '__main__':
  main()
