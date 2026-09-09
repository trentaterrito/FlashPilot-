#!/usr/bin/env python3
"""Parked model slot transaction. No execution without explicit approved Linux spec."""
import argparse,fcntl,hashlib,json,os,select,stat,subprocess,sys,time,uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent
PROTECTED=('AlphaLongitudinalEnabled','ModelManager_ActiveBundle','ModelManager_ActiveBundleChestnut')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def durable(path,value):
 p=Path(path);tmp=p.with_suffix('.new')
 with tmp.open('w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)
 fd=os.open(p.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
def load(p):return json.loads(Path(p).read_text())
def command(argv,**kw):return subprocess.run(argv,check=True,text=True,capture_output=True,timeout=60,**kw).stdout.strip()
def pid_identity(pid):
 try:return Path('/proc') .joinpath(str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]
 except OSError:
  if sys.platform == 'linux':return None
  result=subprocess.run(['ps','-p',str(pid),'-o','lstart='],capture_output=True,text=True)
  return result.stdout.strip() or None
class Linux:
 def __init__(self,spec,root):self.s=spec;self.root=Path(root)
 def probe(self,mode):return json.loads(command(['/bin/bash','-c','source /etc/profile; exec \"$@\"','probe',self.s['python'],'-B',str(HERE/'probe.py'),'--source',self.s['runtime'],'--mode',mode]))
 def settings(self):
  return {k:sha(Path('/data/params/d')/k) if (Path('/data/params/d')/k).is_file() else None for k in self.s['protected_keys']}
 def integrity(self):
  if command(['systemctl','cat','comma.service'])!=self.s['unit_text']:raise RuntimeError('original unit drift')
  for p,h in self.s['files'].items():
   if sha(p)!=h:raise RuntimeError('protected source/launcher drift: '+p)
  if command(['git','-C',self.s['runtime'],'rev-parse','HEAD'])!=self.s['runtime_sha']:raise RuntimeError('runtime HEAD drift')
 def artifact(self):
  artifact_guard(self.s['source']).verify_artifact(self.s['model_root'],self.s['artifact'])
 def fresh_output(self):
  if Path(self.s['output']).exists():raise RuntimeError('fresh checker output directory required')
 def stop_empty(self,unit):
  found=subprocess.run(['systemctl','show',unit,'-p','LoadState','-p','ControlGroup'],capture_output=True,text=True,timeout=10)
  properties=dict(line.split('=',1) for line in found.stdout.splitlines() if '=' in line)
  if properties.get('LoadState')=='not-found':return
  if found.returncode or properties.get('LoadState')!='loaded':raise RuntimeError('cannot establish unit state '+unit)
  cg=properties.get('ControlGroup','')
  # KillMode=control-group plus an explicit empty-cgroup check includes descendants.
  subprocess.run(['systemctl','stop',unit],capture_output=True,timeout=60,check=False)
  after=subprocess.run(['systemctl','show',unit,'-p','LoadState','-p','ActiveState'],capture_output=True,text=True,timeout=10)
  stopped=dict(line.split('=',1) for line in after.stdout.splitlines() if '=' in line)
  if stopped.get('LoadState')!='not-found' and (after.returncode or stopped.get('LoadState')!='loaded' or stopped.get('ActiveState') not in ('inactive','failed')):
   raise RuntimeError('cannot prove unit stopped '+unit)
  if cg:
   path=Path('/sys/fs/cgroup')/cg.lstrip('/')
   if path.exists() and any(p.read_text().strip() for p in path.rglob('cgroup.procs')):raise RuntimeError('descendants remain '+unit)
 def owns_native(self,probe):
  group=command(['systemctl','show','comma.service','-p','ControlGroup','--value'])
  memberships=Path('/proc').joinpath(str(probe['native_pid']),'cgroup').read_text().splitlines()
  if not group or not any(line=='0::'+group or line.startswith('0::'+group+'/') for line in memberships):
   raise RuntimeError('Native model is not contained by the original service cgroup')
 def start_blocked(self,unit):
  # Direct foreground launcher; no detached/shared tmux server or service override.
  command(['systemd-run','--unit',unit,'--service-type=exec','--uid=comma','--property=KillMode=control-group',
   '--property=SendSIGKILL=yes','--property=TimeoutStopSec=5','--property=LimitRTPRIO=100','--property=LimitNICE=-10',
   '--working-directory=/usr/comma','--setenv=BLOCK=modeld,modeld_tinygrad','/usr/comma/comma.sh'])
 def start_job(self,unit):
  self.artifact()
  command(['systemd-run','--unit',unit,'--service-type=exec','--uid=comma','--property=KillMode=control-group',
   '--property=SendSIGKILL=yes','--property=TimeoutStopSec=5','--property=RuntimeMaxSec='+str(self.s['job_seconds']),
   '--working-directory='+self.s['job_cwd'],'--setenv=PYTHONPATH='+self.s['runtime'],
   '/bin/bash','-c','source /etc/profile; exec \"$@\"','job',*job_argv(self.s)])
 def job_done(self,unit):
  state=command(['systemctl','show',unit,'-p','ActiveState','--value'])
  return state not in ('active','activating'),command(['systemctl','show',unit,'-p','Result','--value'])
 def start_native(self):command(['systemctl','start','comma.service'])

def artifact_guard(source):
 import importlib.util
 definition=importlib.util.spec_from_file_location('selected_artifact_guard',Path(source)/'openpilot/sunnypilot/models/artifact.py')
 identity=importlib.util.module_from_spec(definition);definition.loader.exec_module(identity)
 return identity

def job_argv(s):
 return [s['python'],'-u',str(HERE/'shared_model_check.py'),'run','--spec',s['checker_spec'],
         '--spec-sha256',s['checker_spec_sha256'],'--ref',s['ref'],'--source',s['source'],
         '--runtime',s['runtime'],'--model-root',s['model_root'],'--output',s['output'],
         '--seconds','15','--transaction-id',s['transaction_id'],'--authorize-production-publishers']

def recover(root,backend):
 root=Path(root);state=load(root/'state.json');spec=load(root/'spec.json')
 def save(phase,**kw):
  state.update(phase=phase,**kw);durable(root/'state.json',state)
 def lease_ok():
  try:
   lease=load(root/'lease.json')
   return (lease['pid']>1 and lease['identity'] is not None and 0<=time.monotonic()-lease['heartbeat']<3 and pid_identity(lease['pid'])==lease['identity'] and time.monotonic()<state['deadline'])
  except (OSError,ValueError,KeyError):return False
 def restore(reason):
  save('restoring',reason=reason)
  # This order is invariant, including retries after a restorer crash.
  backend.stop_empty(state['job_unit']);backend.stop_empty(state['blocked_unit'])
  backend.integrity();backend.start_native()
  native=backend.probe('native')
  if backend.settings()!=state['protected_settings']:raise RuntimeError('protected settings changed; no automatic setting rewrite')
  result_path=Path(spec.get('output',root/'unused'))/'RESULT.json'
  try:result=load(result_path) if result_path.is_file() else {}
  except (OSError,ValueError):result={}
  accepted=(state.get('job_completed_successfully',False) and result.get('passed') is True and
   result.get('transaction_id')==spec.get('transaction_id') and spec.get('transaction_id') is not None and
   result.get('requested_ref')==spec['ref'] and result.get('spec_sha256')==spec['checker_spec_sha256'] and
   result.get('expected_sha256')==spec['artifact']['downloadUri']['sha256'])
  save('restored',native=native,completed=True,validation_passed=bool(accepted))
 try:
  if state.get('completed'):return 0
  if state['phase'] not in ('prepared','armed'):
   restore(state.get('reason','recovery_restart_after_disruption'));return 0
  save('armed');durable(root/'armed.json',{'ready':True,'pid':os.getpid()})
  while not (root/'proceed').exists():
   if not lease_ok():save('cancelled_before_disruption',completed=True);return 0
   time.sleep(.1)
  if not lease_ok():save('cancelled_before_disruption',completed=True);return 0
  backend.integrity();backend.artifact();backend.probe('native');backend.fresh_output()
  if not lease_ok():save('cancelled_before_disruption',completed=True);return 0
  save('disruption_intent')  # fsynced BEFORE stop, recoverable at every next instruction.
  backend.stop_empty('comma.service')
  backend.start_blocked(state['blocked_unit']);backend.probe('blocked')
  if not lease_ok():restore('lease_lost_before_job');return 0
  save('job_start_intent');backend.start_job(state['job_unit']);save('running')
  reason=''
  while lease_ok():
   done,result=backend.job_done(state['job_unit'])
   if done:
    reason='job_'+result;save('job_finished',job_completed_successfully=result=='success');break
   backend.probe('parked');time.sleep(.1)
  restore(reason or 'lease_or_deadline_lost');return 0
 except BaseException as e:
  if state['phase'] in ('prepared','armed'):
   save('cancelled_before_disruption',error=repr(e),completed=True);return 1
  save('failure',error=repr(e),attempts=state.get('attempts',0)+1)
  try:restore('failure: '+repr(e))
  except BaseException as final:
   save('recovery_failed',error=repr(final));return 1  # systemd restarts this owner.
  return 0

def verify_spec(s):
 if sys.platform!='linux' or os.geteuid()!=0 or not Path('/run/systemd/system').is_dir() or not Path('/sys/fs/cgroup/cgroup.controllers').exists():raise RuntimeError('root Linux/systemd/cgroup-v2 required')
 for path in [HERE,*HERE.rglob('*.py'),Path(s['source']),*Path(s['source']).rglob('*.py')]:
  info=path.stat()
  if info.st_uid!=0 or info.st_mode&(stat.S_IWGRP|stat.S_IWOTH):raise RuntimeError('stage must be root-owned and immutable to comma')
 if not set(PROTECTED)<=set(s['protected_keys']):raise RuntimeError('missing mandatory protected settings')
 if not 1<=s['job_seconds']<=210 or not 1<=s['deadline_seconds']<=240:raise RuntimeError('unbounded job/deadline')
 for key in ('python','runtime','job_cwd','source','checker_spec','output','model_root'):
  if not Path(s[key]).is_absolute():raise RuntimeError('absolute paths required')
 if s['runtime']=='/data/openpilot' and Path(s['runtime']).is_symlink():raise RuntimeError('unreviewed launcher indirection')
 required=[str(HERE/'transaction.py'),str(HERE/'probe.py'),s['python'],'/usr/comma/comma.sh','/data/continue.sh']
 if not set(required)<=set(s['files']):raise RuntimeError('missing transaction/launcher/interpreter hash pins')
 if 'job_argv' in s:raise RuntimeError('arbitrary worker commands forbidden')
 if sha(s['checker_spec'])!=s['checker_spec_sha256']:raise RuntimeError('checker spec drift')
 checker=load(s['checker_spec'])
 if s['ref'] in checker.get('known_contract_failures',{}):raise RuntimeError('known contract failure excluded')
 from shared_model_check import one_bundle
 _,artifact=one_bundle(checker['catalog'],s['ref'])
 expected_artifact={'fileName':artifact['file_name'],'downloadUri':{'sha256':artifact['download_uri']['sha256']},
  'chunks':[{'fileName':c['file_name'],'sha256':c['sha256']} for c in artifact.get('chunks',[])]}
 for relative,expected in checker['source_files'].items():
  if sha(Path(s['source'])/relative)!=expected:raise RuntimeError('candidate source drift')
 for relative,expected in checker['tool_files'].items():
  if sha(HERE/relative)!=expected:raise RuntimeError('tool drift')
 identity=artifact_guard(s['source'])
 if identity.artifact_identity(expected_artifact)!=identity.artifact_identity(s['artifact']):raise RuntimeError('artifact spec drift')
 if Path(s['output']).exists():raise RuntimeError('fresh checker output directory required')
 if s.get('original_native_model')!='CD210' or s.get('live_approved') is not True:raise RuntimeError('explicit reviewed native baseline/approval required')
 # Reject script-controlled BLOCK or persistent unit overrides in original launch.
 if 'BLOCK' in s['unit_text'] or 'tmux new-session -s comma -d /usr/comma/comma.sh' not in s['unit_text']:raise RuntimeError('unexpected original oneshot launch')

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['launch','recover']);p.add_argument('--state',type=Path,required=True);p.add_argument('--spec',type=Path);p.add_argument('--spec-sha256');p.add_argument('--authorize-parked-validation',action='store_true');a=p.parse_args()
 if a.mode=='recover':
  spec=load(a.state/'spec.json')
  # Recovery must not depend on the test artifact or candidate remaining valid.
  if sys.platform!='linux' or os.geteuid()!=0:raise RuntimeError('Linux root recovery required')
  with Path('/run/flashpilot-model-validation.lock').open('w') as f:
   fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);return recover(a.state,Linux(spec,a.state))
 if a.spec is None:p.error('--spec required')
 if not a.spec_sha256 or sha(a.spec)!=a.spec_sha256:raise RuntimeError('reviewed transaction spec hash required')
 spec=load(a.spec);spec['live_approved']=a.authorize_parked_validation;verify_spec(spec)
 if a.state.exists():raise RuntimeError('fresh durable state directory required')
 with Path('/run/flashpilot-model-validation.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 a.state.mkdir(mode=0o700,parents=False);backend=Linux(spec,a.state)
 backend.integrity();backend.artifact();before=backend.probe('native');backend.owns_native(before)
 for key in ('ModelManager_ActiveBundle','ModelManager_ActiveBundleChestnut'):
  file=Path('/data/params/d')/key
  if file.is_file() and file.read_bytes().strip() not in (b'',b'{}',b'null'):raise RuntimeError('original selection is not native default')
 token=uuid.uuid4().hex[:12];unit='fp-model-recovery-'+token;spec['transaction_id']=token
 state={'phase':'prepared','deadline':time.monotonic()+spec['deadline_seconds'],'job_unit':'fp-model-job-'+token,
  'blocked_unit':'fp-model-blocked-'+token,'protected_settings':backend.settings(),'native_before':before,'completed':False}
 durable(a.state/'spec.json',spec);durable(a.state/'state.json',state)
 def beat():durable(a.state/'lease.json',{'pid':os.getpid(),'identity':pid_identity(os.getpid()),'heartbeat':time.monotonic()})
 beat()
 command(['systemd-run','--unit',unit,'--service-type=exec','--property=Restart=on-failure','--property=RestartSec=2',
  '--property=StartLimitIntervalSec=0','--property=KillMode=control-group',spec['python'],'-B',str(HERE/'transaction.py'),'recover','--state',str(a.state.resolve())])
 # This foreground SSH lease owner never stops/starts vehicle services itself.
 start=time.monotonic()
 while not (a.state/'armed.json').exists():
  if time.monotonic()-start>15:
   durable(a.state/'lease.json',{'pid':0,'identity':None,'heartbeat':0})
   raise RuntimeError('recovery did not arm; no disruption authorized')
  beat();time.sleep(.1)
 (a.state/'proceed').touch()
 try:
  while not load(a.state/'state.json').get('completed'):
   readable,_,_=select.select([sys.stdin],[],[],.25)
   if readable and not os.read(sys.stdin.fileno(),1):break  # SSH pipe EOF expires lease.
   beat()
 finally:
  durable(a.state/'lease.json',{'pid':0,'identity':None,'heartbeat':0})
 print(json.dumps({'state':str(a.state),'recovery_unit':unit,'result':load(a.state/'state.json')}));return 0
if __name__=='__main__':raise SystemExit(main())
