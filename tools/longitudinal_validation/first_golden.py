"""Explicit, provenance-gated first measurements; never regression or promotion."""
import importlib.metadata
from pathlib import Path

from . import engine
from .comparison import compare_records, compute_metrics
from .provenance import canonical_hash, check_sha, digest, finite_tree, require, runtime_identity, source_identity
from .runtime_identity import qualify_route, validate_identity

MODE = 'FIRST_GOLDEN_MEASURE'
STATUS = 'UNREVIEWED_BASELINE_MEASUREMENT'
QUALIFIED = 'MODEL_RUNTIME_PROVENANCE_QUALIFIED_NOT_GOLDEN_APPROVAL'
REPLAY_FIELDS = {'case_id', 'segment_ids', 'score_start_ns', 'score_end_ns', 'dt', 'join_policy',
                 'initialization', 'schedule_sha256', 'tick_count', 'first_tick_ns', 'last_tick_ns'}


def validate_request(request):
  finite_tree(request)
  require(isinstance(request, dict) and set(request) ==
          {'version', 'mode', 'route_id', 'segments', 'qualification', 'identities', 'replay'},
          'measurement request fields incomplete/unknown; acceptance and promotion forbidden')
  require(type(request['version']) is int and request['version'] == 1 and request['mode'] == MODE,
          'explicit FIRST_GOLDEN_MEASURE mode required')
  route = request['route_id']
  require(isinstance(route, str) and route and '/' not in route and '..' not in route, 'invalid route identity')
  segments = request['segments']
  require(isinstance(segments, list) and segments, 'missing complete route segments')
  for i, segment in enumerate(segments):
    require(isinstance(segment, dict) and set(segment) == {'id', 'path', 'sha256', 'size_bytes'}, 'segment fields incomplete')
    require(type(segment['id']) is int and segment['id'] == i, 'complete contiguous route from segment0 required')
    path = Path(segment['path'])
    require(path.is_absolute() and '..' not in path.parts and path.name == 'rlog.zst' and
            path.parent.name == f'{route}--{i}', 'route/segment/full-rlog path mismatch')
    check_sha(segment['sha256'])
    require(type(segment['size_bytes']) is int and segment['size_bytes'] > 0, 'missing segment size')
  q = request['qualification']
  require(isinstance(q, dict) and q.get('status') == QUALIFIED, 'route provenance PASS required')
  require(q.get('rlogs') == [{'path': str(Path(s['path']).resolve()), 'sha256': s['sha256']} for s in segments],
          'complete qualification/segment hash binding mismatch')
  cp = q.get('carparams_identity', {})
  require(cp.get('method') == 'schema_bound_complete_wire_tree_v1', 'canonical CarParams qualification required')
  check_sha(cp.get('canonical_sha256'))
  require(type(q.get('publication_groups')) is int and q['publication_groups'] > 0, 'missing publication qualification')
  identities = request['identities']
  require(isinstance(identities, list) and identities, 'missing loaded identities')
  for identity in identities:
    validate_identity(identity)
    require(identity['fallback']['state'] == 'none_observed', 'first measurement requires one unambiguous non-fallback load')
  hashes = sorted(canonical_hash(value) for value in identities)
  require(len(hashes) == len(set(hashes)) and hashes == q.get('identity_sha256'), 'loaded identity/qualification mismatch')
  require(len(q.get('load_ids', [])) == 1 and {x['load_id'] for x in identities} == set(q['load_ids']),
          'first measurement requires one qualified load')
  replay = request['replay']
  require(isinstance(replay, dict) and set(replay) == REPLAY_FIELDS, 'replay fields incomplete/unknown')
  require(isinstance(replay['case_id'], str) and replay['case_id'].strip(), 'missing case name')
  ids = replay['segment_ids']
  require(isinstance(ids, list) and ids and all(type(x) is int for x in ids) and
          ids == list(range(ids[0], ids[-1]+1)) and 0 <= ids[0] <= ids[-1] < len(segments),
          'incomplete recurrent segment interval')
  require(replay['dt'] == .05 and replay['join_policy'] == 'recorded-plan-trigger/latest-before-plan-v1' and
          replay['initialization'] == 'fresh-planner/full-listed-segment-preroll', 'unsupported recurrence method')
  for key in ('score_start_ns', 'score_end_ns', 'first_tick_ns', 'last_tick_ns', 'tick_count'):
    require(type(replay[key]) is int and replay[key] > 0, f'invalid replay {key}')
  require(replay['first_tick_ns'] < replay['score_start_ns'] < replay['score_end_ns'] <= replay['last_tick_ns'],
          'missing preroll/scoring interval')
  check_sha(replay['schedule_sha256'])
  return request


def verify_files(request):
  for segment in request['segments']:
    path = Path(segment['path'])
    require(path.is_file(), f'missing full rlog: {path}')
    require(not list(path.parent.glob('*.lock')), f'route still recording: {path.parent}')
    require(path.stat().st_size == segment['size_bytes'] and digest(path) == segment['sha256'], f'rlog hash/size mismatch: {path}')


def verify_environment(root, identity):
  """Bind the existing replay runtime to every recorded model/runtime field."""
  root = Path(root).resolve()
  recorded = identity['environment']
  source, runtime = source_identity(root), runtime_identity(root)
  expected_source = recorded['source']
  for key in ('sha', 'opendbc_sha', 'submodules', 'schema_files'):
    require(source[key] == expected_source[key], f'recorded source mismatch: {key}')
  for path, sha in expected_source['files'].items():
    require(digest(root / path) == sha, f'recorded source file mismatch: {path}')
  expected_runtime = recorded['runtime']
  for key in runtime:
    expected = expected_runtime[key]
    if key == 'packages': expected = {k: expected[k] for k in runtime[key]}
    require(runtime[key] == expected, f'recorded solver/runtime mismatch: {key}')
  # The model receipt also records tinygrad, absent from the older replay ABI.
  try:
    tinygrad = {'installed': True, 'version': importlib.metadata.version('tinygrad')}
  except importlib.metadata.PackageNotFoundError:
    tinygrad = {'installed': False, 'version': None}
  require(tinygrad == expected_runtime['packages']['tinygrad'], 'recorded tinygrad runtime mismatch')
  return source, runtime


def admit(root, request):
  """No saved PASS is trusted without unchanged qualification of actual bytes."""
  request = validate_request(request)
  engine.runtime_guard(root)
  verify_files(request)
  # LogReader and schema must come from the exact source, not a host fallback.
  import sys
  root = Path(root).resolve()
  sys.path[:0] = [str(root), str(root/'opendbc_repo'), str(root/'msgq_repo')]
  source, runtime = verify_environment(root, request['identities'][0])
  qualification = qualify_route([s['path'] for s in request['segments']], str(root))
  require(qualification == request['qualification'], 'recomputed route provenance differs from qualified binding')
  for identity in request['identities']:
    require(identity['environment'] == request['identities'][0]['environment'], 'loaded environment ambiguity')
  engine.runtime_guard(root)
  return qualification, source, runtime


def measurement_result(request, qualification, source, runtime, rows, recorded, recurrence, ticks):
  comparison = compare_records(recorded, rows)
  # Onsets already negative at the first scoring sample are left-censored, not
  # evidence of matching true braking onset. Keep crossings and censoring apart.
  def crossings(values):
    return [b['t_ns'] for a,b in zip(values, values[1:]) if b['a_target'] < -.03 <= a['a_target']]
  actual, replayed = crossings(recorded), crossings(rows)
  return {'status': STATUS, 'mode': MODE, 'request': request, 'request_sha256': canonical_hash(request),
          'qualification': qualification, 'source': source, 'runtime': runtime,
          'case_name': request['replay']['case_id'], 'rows': rows, 'recorded_rows': recorded,
          'recurrence_sha256': recurrence, 'recurrent_ticks': ticks,
          'source_agreement': sum(a['source']==b['source'] for a,b in zip(recorded,rows))/len(rows),
          'metrics': compute_metrics(rows), 'recorded_comparison': comparison,
          'negative_request_timing': {'threshold_mps2': -.03, 'recorded_crossings_ns': actual,
            'replay_crossings_ns': replayed, 'recorded_left_censored': recorded[0]['a_target'] < -.03,
            'replay_left_censored': rows[0]['a_target'] < -.03,
            'paired_delta_s': [(b-a)*1e-9 for a,b in zip(actual,replayed)] if len(actual)==len(replayed) else None},
          'golden_approved': False, 'regression_baseline_eligible': False,
          'limitations': ['No tolerance, golden acceptance, promotion or vehicle-safety decision is produced.',
            'Original latest-before-plan publication join; actual SubMaster consumption is not logged.',
            'Fresh planner with uninterrupted full-listed-segment preroll, not logged-state injection.',
            'Spacing is recorded/exogenous; jerk is target jerk, not counterfactual vehicle behavior.',
            'Recorded comparison solver/danger fields are replay-derived; original shadow telemetry is diagnostic only.']}


def measure(root, request):
  qualification, source, runtime = admit(root, request)
  planner_module, mpc_module = engine.load_runtime(root)
  engine.verify_loaded_solver(root, runtime)
  events = engine.read_events(request['segments'], request['replay']['segment_ids'])
  cp_events = engine.read_events(request['segments'], [0])
  raw, context, init = engine.cp_from_events(cp_events)
  ticks, timing = engine.schedule(events)
  require(all(request['replay'][k] == v for k,v in timing.items()), 'recurrent timing mismatch')
  require(float(planner_module.DT_MDL) == request['replay']['dt'], 'planner cadence mismatch')
  with context as cp:
    evidence = engine.evidence_metadata(events, raw, cp, init)
  # Get a fresh CP reader for the common numerical core, which owns its context.
  raw, context, init = engine.cp_from_events(cp_events)
  m = {'source': source, 'runtime': runtime, 'evidence': evidence, 'replay': request['replay']}
  rows, recorded, recurrence = engine.collect_replay(root, m, planner_module, mpc_module, events, ticks, raw, context, init)
  verify_files(request)
  require(verify_environment(root, request['identities'][0]) == (source,runtime), 'source/runtime drift during measurement')
  engine.runtime_guard(root)
  return measurement_result(request, qualification, source, runtime, rows, recorded, recurrence, len(ticks))


def measure_twice(root, request, invoke, ssh=None, python=None, bundle=None):
  validate_request(request)
  first = invoke(root, 'first_golden_measure', request, ssh, python, bundle)
  if first.get('status') != STATUS: return first
  second = invoke(root, 'first_golden_measure', request, ssh, python, bundle)
  if second.get('status') != STATUS:
    return {'status': 'BLOCKED', 'mode': MODE, 'error': 'second independent measurement blocked',
            'first_measurement': first, 'second_measurement': second}
  identical = (first['recurrence_sha256'] == second['recurrence_sha256'] and
               first['recurrent_ticks'] == second['recurrent_ticks'] and canonical_hash(first['rows']) == canonical_hash(second['rows']))
  first['repeat_measurement'] = {'identical': identical, 'status': second['status'],
    'recurrence_sha256': second['recurrence_sha256'], 'rows_sha256': canonical_hash(second['rows']),
    'recorded_comparison': second['recorded_comparison']}
  # Non-repeatability is measured and explicitly retained, never turned into a
  # numerical tolerance or automatic baseline acceptance.
  return first
