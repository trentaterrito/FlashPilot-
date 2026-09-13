import copy
import hashlib
import struct
from pathlib import Path

import capnp
import pytest
from opendbc.car.structs import car
import opendbc.car.structs as structs

from tools.longitudinal_validation.carparams_identity import SCHEMA_NODE_ID, fingerprint, validate_proof, wire_tree
from tools.longitudinal_validation.provenance import ValidationError
from tools.longitudinal_validation.runtime_identity import qualify_normalized
from tools.longitudinal_validation.tests.test_runtime_identity import fixture

SCHEMA = hashlib.sha256(Path(structs.__file__).with_name('car.capnp').read_bytes()).hexdigest()


def fp(raw):
  return fingerprint(raw, SCHEMA)


def padded(raw, value=0):
  result = bytearray(raw + struct.pack('<Q', value))
  struct.pack_into('<I', result, 4, (len(result)-8)//8)
  return bytes(result)


def sample():
  return car.CarParams.new_message(carFingerprint='FORD_F_150_LIGHTNING_MK1', mass=3100,
                                  wheelbase=3.68, steerRatio=16.9, openpilotLongitudinalControl=True,
                                  longitudinalActuatorDelay=.15, flags=2,
                                  safetyConfigs=[{'safetyModel': 'ford', 'safetyParam': 6}])


def test_relocated_objects_and_zero_arena_only():
  a = sample(); a.brand = 'ford'
  b = car.CarParams.new_message(brand='ford'); b.from_dict(a.to_dict())
  raw = a.to_bytes(); other = b.to_bytes()
  assert fp(raw)['canonical_sha256'] == fp(other)['canonical_sha256']
  assert fp(raw)['canonical_sha256'] == fp(padded(raw))['canonical_sha256']
  assert fp(raw)['raw_sha256'] != fp(padded(raw))['raw_sha256']


@pytest.mark.parametrize('name,value', [('mass', 3200), ('wheelbase', 3.7), ('steerRatio', 17.1),
  ('longitudinalActuatorDelay', .2), ('openpilotLongitudinalControl', False), ('flags', 3),
  ('radarUnavailable', True), ('radarDelay', .2), ('carFingerprint', 'other'), ('brand', 'other')])
def test_relevant_fields_never_ignored(name, value):
  before = sample(); after = sample(); setattr(after, name, value)
  assert fp(before.to_bytes())['canonical_sha256'] != fp(after.to_bytes())['canonical_sha256']


def test_safety_and_metadata_not_ignored():
  a,b = sample(),sample(); b.safetyConfigs[0].safetyParam = 7
  assert fp(a.to_bytes())['canonical_sha256'] != fp(b.to_bytes())['canonical_sha256']
  a,b = sample(),sample(); b.carVin = 'metadata-still-included'
  assert fp(a.to_bytes())['canonical_sha256'] != fp(b.to_bytes())['canonical_sha256']


def test_null_and_present_empty_remain_distinct():
  a,b = sample(),sample(); b.brand = ''
  assert fp(a.to_bytes())['canonical_sha256'] != fp(b.to_bytes())['canonical_sha256']


def test_unknown_nonzero_data_bit():
  raw = bytearray(car.CarParams.new_message().to_bytes())
  # Top bit of final root data word is not described by the pinned schema.
  raw[16 + 18*8 - 1] |= 0x80
  with pytest.raises(ValidationError, match='unknown/unclassified'):
    fp(bytes(raw))


def test_unknown_pointer_slot_even_zero_is_not_silently_ignored():
  raw = bytearray(car.CarParams.new_message().to_bytes())
  ptr = struct.unpack_from('<Q', raw, 8)[0]
  struct.pack_into('<Q', raw, 8, ptr + (1 << 48))
  with pytest.raises(ValidationError, match='unknown/unclassified'):
    fp(padded(bytes(raw)))


@pytest.mark.parametrize('mutation,match', [
  (lambda raw: raw[:-1], 'byte length'),
  (lambda raw: b'', 'byte length'),
  (lambda raw: raw + b'\x00'*8, 'framing'),
  (lambda raw: b'\x01\x00\x00\x00' + raw[4:], 'framing'),
  (lambda raw: padded(raw, 1), 'unreachable'),
])
def test_malformed_and_unclassified_bytes_fail(mutation, match):
  with pytest.raises(ValidationError, match=match): fp(mutation(sample().to_bytes()))


@pytest.mark.parametrize('root,match', [(2, 'far/capability'), (3, 'far/capability'),
  ((1 << 32) | (10000 << 2), 'out of bounds'), ((1 << 32) | 0xfffffffc, 'overlapping')])
def test_invalid_pointers(root, match):
  with pytest.raises(ValidationError, match=match):
    wire_tree(struct.pack('<IIQQ', 0, 2, root, 0))


def test_schema_and_decoder_pins(monkeypatch):
  with pytest.raises(ValidationError, match='schema incompatible'): fingerprint(sample().to_bytes(), '0'*64)
  monkeypatch.setattr(capnp, '__version__', '999')
  with pytest.raises(ValidationError, match='decoder version'): fp(sample().to_bytes())


def test_nonfinite_fails():
  a=sample(); a.mass=float('nan')
  with pytest.raises(ValidationError, match='nonfinite'): fp(a.to_bytes())


def normalized_pair(tmp_path):
  records, paths = fixture(tmp_path)
  snapshot = next(x for x in records if x['topic']=='carParamsPersistent')
  snapshot['car_params_sha256'] = '9'*64
  snapshot['canonical_carparams'] = {'version':1, 'schema_sha256':'5'*64, 'canonical_sha256':'a'*64, 'raw_sha256':'9'*64,
                                     'schema_node_id':SCHEMA_NODE_ID, 'size_bytes':272, 'unused_zero_words':[]}
  live = dict(copy.deepcopy(snapshot), topic='carParams', log_mono_ns=620, car_params_sha256='8'*64)
  live['canonical_carparams']['raw_sha256']='8'*64
  records.append(live)
  return records,paths,snapshot,live


def test_canonical_match_requires_runtime_raw_object(tmp_path):
  records,paths,_,_=normalized_pair(tmp_path)
  result=qualify_normalized(records,paths)
  assert result['carparams_identity']['serialization_only_raw_mismatch']


@pytest.mark.parametrize('failure,match', [('missing','missing canonical/live'), ('canonical','semantic mismatch'),
  ('schema','schema incompatible'), ('raw','raw/proof mismatch'), ('runtime','runtime CarParams hash'), ('late','preceding recorded')])
def test_normalized_proof_failures(tmp_path,failure,match):
  records,paths,snapshot,live=normalized_pair(tmp_path)
  if failure=='missing': records.remove(live)
  if failure=='canonical': live['canonical_carparams']['canonical_sha256']='b'*64
  if failure=='schema': live['canonical_carparams']['schema_sha256']='b'*64
  if failure=='raw': live['canonical_carparams']['raw_sha256']='b'*64
  if failure=='runtime':
    live['car_params_sha256']='b'*64; live['canonical_carparams']['raw_sha256']='b'*64
  if failure=='late': live['log_mono_ns']=1001
  with pytest.raises(ValidationError,match=match): qualify_normalized(records,paths)


@pytest.mark.parametrize('key,value', [('version',True), ('schema_node_id',123), ('size_bytes',False),
  ('size_bytes',273), ('unused_zero_words',[0]), ('unused_zero_words',[1,1]), ('unused_zero_words',[99]),
  ('canonical_sha256','not a hash'), ('extra','unclassified')])
def test_malformed_proof_rejected(key,value):
  proof=fp(sample().to_bytes()); proof[key]=value
  with pytest.raises(ValidationError): validate_proof(proof)


def test_incomplete_proof_rejected():
  proof=fp(sample().to_bytes()); del proof['schema_node_id']
  with pytest.raises(ValidationError): validate_proof(proof)


def test_composite_amplification_rejected():
  # Empty composite structs consume no words but cannot bypass node budget.
  raw=struct.pack('<IIQQ',0,2,1 | (7<<32),40000<<2)
  with pytest.raises(ValidationError,match='amplification'): wire_tree(raw)
