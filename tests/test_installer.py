import os, pathlib, subprocess, tempfile, unittest, struct
ROOT=pathlib.Path(__file__).resolve().parents[1]
SCRIPT=(ROOT/'src/install.sh').read_text()
SHA='dfd4b419f73b2bccbfd0e4d7007124a68ae04c71'
MOCK=r'''#!/usr/bin/env python3
import os,sys,pathlib
args=sys.argv[1:]; case=os.environ['CASE']
path=''
if args[:1]==['-C']: path=args[1]; args=args[2:]
active=bool(path) and pathlib.Path(path).parent.name=='data'
cmd=' '.join(args)
if args[:1]==['init']:
 p=pathlib.Path(path); (p/'launch_openpilot.sh').write_text('never execute'); (p/'launch_openpilot.sh').chmod(0o755)
if args[:1]==['fetch'] and case=='fetch': sys.exit(1)
if args[:2]==['remote','get-url']: print('wrong' if case=='origin' else 'https://github.com/trentaterrito/FlashPilot-.git')
if args[:2]==['rev-parse','FETCH_HEAD']: print('wrong' if case=='immutable-wrong' else 'dfd4b419f73b2bccbfd0e4d7007124a68ae04c71')
if args[:2]==['rev-parse','HEAD']:
 pins={'opendbc_repo':'42fa6447ed0ff9a0497a14ca136ea45d923c1106','panda':'8bcae70c896bf3aee98b28641755f82b4aa5bf8b','msgq_repo':'0e266c1dbcf7328beee3e57b4a8688555387c877','rednose_repo':'28d4a7f69e80e1c3e0d24ca0733d7daeaeade3d0','teleoprtc_repo':'1aa8fc433bef1519a95c0700c96258c3be6dfb34','tinygrad_repo':'e837e367aac9e1a66e689f4f32ce20ca9367df13'}
 print('wrong' if case=='head' or case==path or (case=='active-head' and active) else pins.get(path,'dfd4b419f73b2bccbfd0e4d7007124a68ae04c71'))
if args[:1]==['checkout'] and case=='checkout': sys.exit(1)
if args[:2]==['symbolic-ref','--short']: print('wrong' if case=='branch' or (case=='active-branch' and active) else 'flashpilot-dev')
if args[:2]==['submodule','update'] and case=='submodule-fetch': sys.exit(1)
if args[:2]==['submodule','status']: print('+wrong submodule' if case=='recursive' else ' correct submodule')
if args[:1]==['status'] and (case=='dirty' or (case=='active-dirty' and active)): print(' M dirty')
if args[:2]==['lfs','ls-files'] and case=='lfs-pointer': print('0123456789 - model.onnx')
if args[:2]==['lfs','pull'] and case=='lfs': sys.exit(1)
'''
class InstallerTests(unittest.TestCase):
 def run_case(self,case):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d); data=root/'data'; data.mkdir(); (data/'params/d').mkdir(parents=True); bindir=root/'bin'; bindir.mkdir()
   git=bindir/'git'; git.write_text(MOCK); git.chmod(0o755)
   script=SCRIPT.replace('readonly ROOT=/data','readonly ROOT='+str(data)).replace('[[ -f /AGNOS ]]','[[ -d "$ROOT" ]]')
   (root/'install.sh').write_text(script)
   if case=='existing': (data/'openpilot').mkdir(); (data/'openpilot'/'sentinel').write_text('StarPilot')
   result=subprocess.run(['/bin/bash',str(root/'install.sh')],env={**os.environ,'CASE':case,'PATH':str(bindir)+':/usr/bin:/bin'},capture_output=True)
   log=(data/f'flashpilot-install-{SHA}.log').read_text()
   if case=='success':
    self.assertEqual(result.returncode,0,log)
    self.assertTrue((data/'openpilot'/'launch_openpilot.sh').exists())
    launcher=data/'continue.sh'
    self.assertEqual(launcher.read_text(),'#!/usr/bin/env bash\n\nexport FLASHPILOT_ANGLE_ENABLED=1\n\ncd /data/openpilot\nexec ./launch_openpilot.sh\n')
    self.assertTrue(launcher.stat().st_mode & 0o111)
    self.assertEqual((data/'params/d/SshEnabled').read_text(),'1')
    self.assertEqual((data/'params/d/GithubSshKeys').read_text(),'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMd/x4lkzsLcefKb8A46npmgxxo5dda7Sw2DnuyY7Luz trentterrito@gmail.com\n')
    self.assertEqual((data/'params/d/SshEnabled').stat().st_mode & 0o777,0o600)
    self.assertEqual((data/'params/d/GithubSshKeys').stat().st_mode & 0o777,0o600)
    self.assertIn('MANAGED_BOOTSTRAP PENDING',log)
   else:
    self.assertNotEqual(result.returncode,0,log)
    self.assertFalse((data/'continue.sh').exists())
    if case=='existing': self.assertEqual((data/'openpilot'/'sentinel').read_text(),'StarPilot')
    else: self.assertFalse((data/'openpilot').exists())
 def test_cases(self):
  for case in ['success','existing','fetch','immutable-wrong','origin','checkout','head','branch','submodule-fetch','recursive','dirty','lfs','opendbc_repo','panda','msgq_repo','rednose_repo','teleoprtc_repo','tinygrad_repo','active-head','active-branch','active-dirty','lfs-pointer']:
   with self.subTest(case=case): self.run_case(case)
 def test_elf(self):
  b=(ROOT/'dist/flashpilot-dfd4b419-installer-v4-diagnostic').read_bytes()
  h=struct.unpack_from('<16sHHIQQQIHHHHHH',b)
  self.assertEqual(h[0][:7],b'\x7fELF\x02\x01\x01'); self.assertEqual(h[1:4],(2,183,1)); self.assertEqual(h[4],0x401000)
  self.assertEqual(b[0x1000:0x1004],bytes.fromhex('e30340f9'))
  self.assertIn(SCRIPT.encode()+b'\0',b)
  self.assertEqual(h[10],2)
 def test_immutable_fetch_ignores_mutable_branch_head(self):
  self.assertIn('fetch --depth=1 origin "$SHA"',SCRIPT)
  self.assertIn('git checkout -B "$BRANCH" "$SHA"',SCRIPT)
  self.assertNotIn('git clone --depth=1 --single-branch --branch "$BRANCH"',SCRIPT)
 def test_launcher_exports_selector_to_managed_child(self):
  launcher_text='#!/usr/bin/env bash\n\nexport FLASHPILOT_ANGLE_ENABLED=1\n\ncd /data/openpilot\nexec ./launch_openpilot.sh\n'
  for lifecycle,parent_value in [('managed-restart','0'),('reboot',None),('ignition-cycle','invalid')]:
   with self.subTest(lifecycle=lifecycle), tempfile.TemporaryDirectory() as d:
    root=pathlib.Path(d); openpilot=root/'openpilot'; openpilot.mkdir(); observed=root/'observed'
    child=openpilot/'launch_openpilot.sh'
    child.write_text('#!/usr/bin/env bash\nprintf "%s" "$FLASHPILOT_ANGLE_ENABLED" > "'+str(observed)+'"\n')
    child.chmod(0o755)
    launcher=root/'continue.sh'
    launcher.write_text(launcher_text.replace('/data/openpilot',str(openpilot)))
    launcher.chmod(0o755)
    env=os.environ.copy()
    if parent_value is None: env.pop('FLASHPILOT_ANGLE_ENABLED',None)
    else: env['FLASHPILOT_ANGLE_ENABLED']=parent_value
    result=subprocess.run(['/bin/bash',str(launcher)],env=env,capture_output=True)
    self.assertEqual(result.returncode,0,result.stderr.decode())
    self.assertEqual(observed.read_text(),'1')
if __name__=='__main__': unittest.main(verbosity=2)
