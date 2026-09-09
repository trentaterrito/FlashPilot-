"""Exercise alternate main through native message publication without a vehicle/GPU.

Camera/message transport, model computation and process side effects are
substituted. Real ModelState selection opens a synthetic artifact from a temporary
model directory. Native Params, enums, service registry, schema, action extraction,
helpers and serializers remain real. This does not validate catalog model weights.
"""
from types import SimpleNamespace
import numpy as np
import pytest
from openpilot.cereal import custom, log
from openpilot.cereal.services import SERVICE_LIST
from openpilot.common.params import Params
from openpilot.common.hardware.hw import Paths
from openpilot.selfdrive.modeld.helpers import dump_oob
from openpilot.sunnypilot.modeld_v2 import modeld as runner
from openpilot.sunnypilot.modeld_v2 import modeld_base, meta_helper
from openpilot.sunnypilot.modeld_v2.constants import ModelConstants

class Finished(Exception):
  pass

def outputs():
  plan=np.zeros((1,33,15),dtype=np.float32)
  plan[0,:,0]=np.array(ModelConstants.T_IDXS)*20
  plan[0,:,3]=20
  return dict(plan=plan,plan_stds=np.ones_like(plan)*.1,
    lane_lines=np.zeros((1,4,33,2)),lane_lines_stds=np.ones((1,4,33,2))*.1,lane_lines_prob=np.ones((1,8))*.8,
    road_edges=np.zeros((1,2,33,2)),road_edges_stds=np.ones((1,2,33,2))*.1,
    lead=np.zeros((1,3,6,4)),lead_stds=np.ones((1,3,6,4)),lead_prob=np.zeros((1,3)),
    desire_state=np.zeros((1,8)),desire_pred=np.zeros((1,4,8)),meta=np.zeros((1,55)),
    pose=np.array([[20.,0,0,0,0,0]]),pose_stds=np.ones((1,6))*.1,
    wide_from_device_euler=np.zeros((1,3)),wide_from_device_euler_stds=np.ones((1,3))*.1,
    road_transform=np.array([[0.,0,1.22]]),road_transform_stds=np.ones((1,3))*.1)

def assert_finite(value):
  if isinstance(value, dict):
    for item in value.values():
      assert_finite(item)
  elif isinstance(value, (list, tuple)):
    for item in value:
      assert_finite(item)
  elif isinstance(value, float):
    assert np.isfinite(value)


@pytest.mark.parametrize('wide_only',[False,True])
@pytest.mark.parametrize('is_20hz',[False,True])
def test_current_runtime_startup_through_publication(monkeypatch,tmp_path,wide_only,is_20hz):
  emitted=[];subscribers=[];models=[]
  params=Params(str(tmp_path/'params'))
  params.put('LagdValueCache',.2,block=True)
  # Both the selected artifact and a decoy exist; the selected one must open.
  model_path=tmp_path/'selected_fixture.pkl'
  for path, marker in ((model_path,'selected'),(tmp_path/'unselected_fixture.pkl','decoy')):
    with path.open('wb') as file:
      dump_oob({'fixture_marker':marker},file)
  bundle=custom.ModelManagerSP.ModelBundle(
    minimumSelectorVersion=19,runner='tinygrad',is20hz=is_20hz,generation=12,
    overrides=[{'key':'lat','value':'.1'},{'key':'long','value':'.3'}],
    models=[{'type':'chunked','artifact':{'fileName':model_path.name}}])
  monkeypatch.delenv('COMBINED_MODEL_PKL',raising=False)
  monkeypatch.setattr(Paths,'model_root',staticmethod(lambda:str(tmp_path)))
  monkeypatch.setattr(runner,'get_active_bundle',lambda **kwargs:bundle)
  monkeypatch.setattr(meta_helper,'get_active_bundle',lambda:bundle)
  monkeypatch.setattr(modeld_base,'Params',lambda:params)
  streams=runner.VisionStreamType
  class Camera:
    width=1928;height=1208;buffer_len=1
    @staticmethod
    def available_streams(*args,**kwargs):
      return [streams.VISION_STREAM_WIDE_ROAD] if wide_only else [streams.VISION_STREAM_NARROW_ROAD,streams.VISION_STREAM_WIDE_ROAD]
    def __init__(self,*args):self.frame_id=0;self.timestamp_sof=0;self.timestamp_eof=0
    def connect(self,*args):return True
    def recv(self):
      self.frame_id+=1;self.timestamp_sof=self.frame_id*50_000_000;self.timestamp_eof=self.timestamp_sof+10_000_000
      return object()
  class Model(runner.ModelState):
    constants=ModelConstants;LONG_SMOOTH_SECONDS=.3;LAT_SMOOTH_SECONDS=.1
    MIN_LAT_CONTROL_SPEED=.3;mlsim=False;chestnut=False
    desire_key='desire';vision_input_names=['input_imgs','big_input_imgs']
    numpy_inputs={'lateral_control_params':np.zeros(2)};PLANPLUS_CONTROL=1.;lat_delay=.2
    get_action_from_model=runner.ModelState.get_action_from_model
    def _init_combined(self,path,cam_w,cam_h,bundle):
      # Stop at the hardware boundary: this is a synthetic artifact, not weights.
      assert runner._load_jits(path)=={'fixture_marker':'selected'}
      self.loaded_path=path
      models.append(self)
    def run(self,bufs,transforms,inputs,prepare_only):
      assert all(np.isfinite(x).all() for x in transforms.values())
      assert np.linalg.norm(transforms['input_imgs'])>0
      self.last_delay=float(inputs['lateral_control_params'][1])
      return None if prepare_only else outputs()
  class Subscriber:
    def __init__(self,names,**kwargs):
      assert set(names)<=SERVICE_LIST.keys()
      assert kwargs['frequency']==ModelConstants.MODEL_FREQ
      subscribers.append(self);self.frame=0
      self.data={name:getattr(runner.messaging.new_message(name),name) for name in names}
      self.data['deviceState'].deviceType='mici'
      self.data['narrowRoadCameraState'].sensor='os04c10'
      self.data['extrinsicsCalibration'].rpyCalib=[0.,0.,0.]
      self.data['extrinsicsCalibration'].height=[1.22]
      self.data['carState'].vEgo=20.
      self.data['carState'].standstill=False
      self.data['lateralDelay'].lateralDelay=.27
      self.seen={name:True for name in names};self.updated=self.seen.copy()
    def update(self,*args):
      self.frame+=1;self.data['narrowRoadCameraState'].frameId=self.frame
    def __getitem__(self,key):return self.data[key]
  class Publisher:
    def __init__(self,names):assert set(names)<=SERVICE_LIST.keys()
    def send(self,name,msg):
      assert msg.valid
      raw=msg.to_bytes()
      with log.Event.from_bytes(raw) as event:
        assert event.which()==name
        assert_finite(event.to_dict())
        if name=='modelV2':assert len(event.modelV2.velocity.x)==33 and np.isfinite(event.modelV2.velocity.x).all()
        if name=='cameraOdometry':assert list(event.cameraOdometry.trans)==[20.,0.,0.]
      emitted.append(name)
      if len(emitted)==180:raise Finished()
  monkeypatch.setattr(runner,'VisionIpcClient',Camera)
  monkeypatch.setattr(runner,'ModelState',Model)
  monkeypatch.setattr(runner,'Params',lambda:params)
  monkeypatch.setattr(runner,'SubMaster',Subscriber)
  monkeypatch.setattr(runner,'PubMaster',Publisher)
  monkeypatch.setattr(runner,'chestnut_present',lambda:False)
  monkeypatch.setattr(runner,'config_realtime_process',lambda *a:None)
  monkeypatch.setattr(runner,'setproctitle',lambda *a:None)
  monkeypatch.setattr(runner.sentry,'set_tag',lambda *a:None)
  monkeypatch.setattr(runner,'cloudlog',SimpleNamespace(warning=lambda *a:None,info=lambda *a:None,debug=lambda *a:None,error=lambda *a:None,bind=lambda **k:None))
  with pytest.raises(Finished):runner.main(demo=True)
  assert emitted==['modelV2','drivingModelData','cameraOdometry']*60
  assert subscribers[0].frame==60
  assert models[0].last_delay==pytest.approx(.37)
  assert models[0].loaded_path==str(model_path)


@pytest.mark.parametrize('filename',['selected_a.pkl','selected_b.pkl'])
def test_missing_selected_artifact_does_not_load_another_model(monkeypatch,tmp_path,filename):
  params=Params(str(tmp_path/'params'))
  monkeypatch.setattr(modeld_base,'Params',lambda:params)
  monkeypatch.setattr(Paths,'model_root',staticmethod(lambda:str(tmp_path)))
  monkeypatch.delenv('COMBINED_MODEL_PKL',raising=False)
  bundle=custom.ModelManagerSP.ModelBundle(
    models=[{'type':'chunked','artifact':{'fileName':filename}}])
  monkeypatch.setattr(runner,'get_active_bundle',lambda **kwargs:bundle)
  (tmp_path/'driving_supercombo_tinygrad.pkl').write_bytes(b'decoy')
  with pytest.raises(AssertionError,match='No driving pkl found'):
    runner.ModelState(cam_w=1928,cam_h=1208)

@pytest.mark.parametrize('speed,accel,prior,stop',[
  (0.,-.2,0.,True), (0.,.2,0.,False), (.3,-.2,0.,False),
  (.299,.099,0.,True), (.299,.1,0.,False), (0.,-.2,2.,True),
])
def test_action_stop_uses_current_unsmoothed_contract(speed,accel,prior,stop):
  # A constant-speed plan with opposite a_now yields exactly the requested
  # acceleration from the real helper, including its stop threshold boundary.
  output=outputs()
  output['plan'][0,:,3]=speed
  output['plan'][0,:,6]=-accel
  model=SimpleNamespace(constants=ModelConstants,LONG_SMOOTH_SECONDS=.3,
    LAT_SMOOTH_SECONDS=.1,MIN_LAT_CONTROL_SPEED=.3,generation=12,
    mlsim=False,PLANPLUS_CONTROL=1.)
  previous=log.ModelDataV2.Action(desiredAcceleration=prior,desiredCurvature=0.)
  action=runner.ModelState.get_action_from_model(model,output,previous,.2,.35,speed)
  assert action.shouldStop is stop
  assert np.isfinite(action.desiredAcceleration)
  if prior==2.:
    assert action.desiredAcceleration>0  # stop decision must precede smoothing
