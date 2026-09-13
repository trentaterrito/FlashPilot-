import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

from openpilot.common.producer_consumption import Recorder, ObservedPubMaster, ObservedSubMaster, digest
from openpilot.cereal import log, messaging


class Event:
  def __init__(self, service="carState", timestamp=123, **payload):
    self.service = service
    self.logMonoTime = timestamp
    self.valid = True
    self.producerConsumption = ""
    self.modelRuntimeRef = ""
    self.payload = payload
    self.can = payload.get("can", [])

  def which(self):
    return self.service

  def to_dict(self):
    return {"logMonoTime": self.logMonoTime, "valid": self.valid, self.service: self.payload,
            "producerConsumption": self.producerConsumption, "modelRuntimeRef": self.modelRuntimeRef}


def sm(service="carState", seen=True, updated=True):
  return SimpleNamespace(services=[service], frame=2, seen={service: seen}, updated={service: updated},
                         recv_frame={service: 2}, logMonoTime={service: 123})


def receipt(recorder, service="radarState", master=None):
  event = Event(service)
  recorder.attach(service, event, master)
  return json.loads(event.producerConsumption)


def test_deterministic_epoch_input_and_publication_binding():
  results = []
  for _ in range(2):
    recorder = Recorder("radard", epoch="epoch")
    master = sm("carControl")
    recorder.begin(master)
    recorder.received(master, [Event("carControl", vEgo=12)])
    results.append(receipt(recorder))
  assert results[0] == results[1]
  binding = results[0]["inputs"]["carControl"]["instance"]
  assert binding["receive_ordinal"] == 1
  assert binding["publisher"] is None
  assert binding["publisher_sequence_available"] is False
  assert results[0]["publication_mono_ns"] == 123


def test_exact_upstream_binding_and_stale_consumption():
  card = Recorder("card", epoch="card-init")
  event = Event(vEgo=12)
  card.attach("carState", event)
  rd = Recorder("radard", epoch="radard-init")
  master = sm()
  rd.received(master, [event])
  first = receipt(rd, master=master)
  master.frame += 1
  master.updated["carState"] = False
  rd.begin(master)
  second = receipt(rd, master=master)
  assert first["inputs"]["carState"]["instance"] == second["inputs"]["carState"]["instance"]
  assert not second["inputs"]["carState"]["updated"]
  assert second["previous_receipt_sha256"] == first["receipt_sha256"]
  assert second["inputs"]["carState"]["instance"]["publisher"]["epoch"] == "card-init"


def test_reset_is_explicit_not_reused_epoch():
  first = receipt(Recorder("radard", epoch="first"))
  second = receipt(Recorder("radard", epoch="second"))
  assert first["epoch"] != second["epoch"]
  assert second["publication"] == 1
  assert second["previous_receipt_sha256"] == ""


def test_invalid_upstream_cannot_leave_stale_success():
  rec = Recorder("planner", epoch="fixed")
  master = sm("radarState")
  rec.received(master, [Event("radarState")])
  broken = Event("radarState")
  broken.producerConsumption = "not json"
  rec.received(master, [broken])
  out = receipt(rec, master=master)
  assert not out["qualified"]
  assert out["inputs"]["radarState"]["instance"]["unavailable"]
  rec.received(master, [Event("radarState")])
  assert not receipt(rec, master=master)["qualified"]


def test_can_order_empty_batch_and_initialization_retention():
  a = Event("can", 10, can=[{"address": 0x135, "busTime": 2, "src": 1, "dat": b"abc"}])
  b = Event("can", 20, can=[{"address": 0x3D7, "busTime": 3, "src": 1, "dat": b"def"}])
  rec = Recorder("card", epoch="fixed")
  rec.can_batch([a, b], "fingerprint")
  rec.begin()
  rec.can_batch([], "CI.init")
  out = receipt(rec)
  assert [x["phase"] for x in out["can_batches"]] == ["fingerprint", "CI.init"]
  assert out["can_batches"][1]["event_count"] == 0
  reverse = Recorder("card")
  reverse.can_batch([b, a])
  assert out["can_batches"][0]["sha256"] != receipt(reverse)["can_batches"][0]["sha256"]
  assert receipt(rec)["can_batches"] == out["can_batches"]
  rec.begin()
  assert receipt(rec)["can_batches"] == []


def test_all_declared_can_fields_affect_identity():
  base = Event("can", can=[{"address": 0x135, "busTime": 2, "src": 1, "dat": b"abc"}])
  reference = Recorder._can_identity(base, None)
  for field, value in (("address", 0x136), ("busTime", 3), ("src", 2), ("dat", b"abd")):
    changed = copy.deepcopy(base)
    changed.payload["can"][0][field] = value
    assert Recorder._can_identity(changed, None) != reference


def test_state_snapshot_is_copy_and_failure_is_sticky():
  rec = Recorder("radard")
  state = {"history": [1, 2], "reset_epoch": 0}
  rec.capture_state("before", lambda: state)
  state["history"].append(3)
  assert receipt(rec)["state"]["before"]["history"] == [1, 2]
  rec.capture_state("bad", lambda: {"x": float("nan")})
  assert not receipt(rec)["qualified"]
  rec.begin()
  assert not receipt(rec)["qualified"]


def test_bound_is_unqualified_not_silent_truncation():
  rec = Recorder("card", max_bytes=1200)
  rec.capture_state("big", lambda: {"data": "x" * 2000})
  out = receipt(rec)
  assert not out["qualified"]
  assert out["errors"]


def test_payload_and_existing_model_identity_never_changed():
  event = Event(vEgo=9, aEgo=-0.2)
  event.modelRuntimeRef = "existing-model-proof"
  before = event.to_dict()
  Recorder("card").attach("carState", event)
  after = event.to_dict()
  del before["producerConsumption"]
  del after["producerConsumption"]
  assert before == after


def test_receipt_hash_covers_all_receipt_fields():
  out = receipt(Recorder("card", epoch="same"))
  sha = out.pop("receipt_sha256")
  assert digest(out) == sha


def test_actual_reset_calls_and_initial_snapshot_retained():
  rec = Recorder("radard", epoch="fixed")
  rec.capture_state("initial", lambda: {"filter": 0})
  rec.begin()
  rec.reset("lead0.ttc")
  rec.reset("lead0.ttc")
  out = receipt(rec)
  assert out["state"]["initial"] == {"filter": 0}
  assert out["reset_epochs"] == {"lead0.ttc": 2}
  assert len(out["notes"]) == 2
  rec.begin()
  out = receipt(rec)
  assert "initial" not in out["state"]
  assert out["reset_epochs"]["lead0.ttc"] == 2


def test_nan_input_hash_is_deterministic_not_fabricated_finite_value():
  event = Event("carControl", unused=float("nan"))
  assert digest(event.to_dict()) == digest(event.to_dict())
  rec = Recorder("planner")
  rec.received(sm("carControl"), [event])
  assert receipt(rec)["qualified"]


def test_upstream_tamper_and_sequence_reversal_rejected():
  upstream = Recorder("card", epoch="fixed")
  first, second = Event(), Event()
  upstream.attach("carState", first)
  upstream.attach("carState", second)
  rec = Recorder("radard")
  rec.received(sm(), [second, first])
  assert not receipt(rec)["qualified"]
  tampered = json.loads(second.producerConsumption)
  tampered["step"] += 1
  second.producerConsumption = json.dumps(tampered)
  rec = Recorder("radard")
  rec.received(sm(), [second])
  assert not receipt(rec)["qualified"]


def test_submaster_calls_original_once_before_observer_without_message_reordering():
  calls = []
  rec = Recorder("radard")
  instance = object.__new__(ObservedSubMaster)
  instance.recorder = rec
  messages = [Event(), None, Event(timestamp=124)]
  with patch.object(messaging.SubMaster, "update_msgs", lambda self, cur, msgs: calls.append(("original", cur, msgs))), \
       patch.object(rec, "received", lambda master, msgs, cur: calls.append(("diagnostic", msgs, cur))):
    instance.update_msgs(1.5, messages)
  assert [x[0] for x in calls] == ["original", "diagnostic"]
  assert calls[0][2] is messages and calls[1][1] is messages
  assert calls[1][2] == 1.5


def test_diagnostic_exception_does_not_suppress_or_duplicate_publish():
  rec = Recorder("card")
  pm = object.__new__(ObservedPubMaster)
  pm.recorder, pm.observed, pm.sm = rec, {"carState"}, None
  event = Event(vEgo=1)
  event.producerConsumption = "stale success"
  sent = []
  with patch.object(rec, "attach", side_effect=ValueError("diagnostic only")), \
       patch.object(messaging.PubMaster, "send", lambda self, service, msg: sent.append((service, msg))):
    pm.send("carState", event)
    pm.send("sendcan", event)
  assert sent == [("carState", event), ("sendcan", event)]
  assert rec.errors
  assert event.producerConsumption == ""


def test_real_capnp_header_only_delta_and_reproducible_binding():
  event = messaging.new_message("carState")
  event.logMonoTime = 123
  event.carState.vEgo = 12.25
  event.carState.aEgo = -0.5
  event.modelRuntimeRef = "existing-model-reference"
  original = event.to_dict()
  Recorder("card", epoch="fixed").attach("carState", event)
  assert event.producerConsumption
  with log.Event.from_bytes(event.to_bytes()) as readback:
    decoded = readback.to_dict()
    original.pop("producerConsumption", None)
    decoded.pop("producerConsumption", None)
    assert decoded == original
    rec = Recorder("radard", epoch="fixed")
    rec.received(sm(), [readback])
    output = receipt(rec)
    assert output["qualified"]
    assert output["inputs"]["carState"]["instance"]["content_sha256"] == digest(event.to_dict())


def test_real_can_raw_and_decoded_identity_and_wire_hash():
  event = messaging.new_message("can", 1)
  event.logMonoTime = 123
  event.can[0].address = 0x135
  event.can[0].src = 1
  event.can[0].dat = bytes(range(24))
  raw = event.to_bytes()
  rec = Recorder("card")
  rec.can_batch([raw])
  batch = receipt(rec)["can_batches"][0]
  import hashlib
  assert batch["events"][0]["wire_sha256"] == hashlib.sha256(raw).hexdigest()
  with log.Event.from_bytes(raw) as decoded:
    assert batch["events"][0]["content_sha256"] == Recorder._can_identity(decoded, None)["content_sha256"]


def test_post_publication_initialization_batches_and_notes_survive_next_begin():
  rec = Recorder("card", epoch="fixed")
  rec.can_batch([], "startup")
  rec.begin()
  first = receipt(rec)
  assert [x["phase"] for x in first["can_batches"]] == ["startup"]
  rec.can_batch([Event("can", can=[])], "CI.init")
  rec.reset("CI.init")
  rec.begin()
  second = receipt(rec)
  assert [x["phase"] for x in second["can_batches"]] == ["CI.init"]
  assert second["notes"] == [{"label": "reset", "step": 1, "value": {"component": "CI.init", "epoch": 1}}]
  # Every selected publication in the same step retains the common evidence.
  third = receipt(rec)
  assert third["can_batches"] == second["can_batches"]
  rec.begin()
  fourth = receipt(rec)
  assert fourth["can_batches"] == [] and fourth["notes"] == []


def test_retired_upstream_epoch_cannot_revive():
  a, b = Recorder("card", epoch="a"), Recorder("card", epoch="b")
  rec = Recorder("radard")
  for producer in (a, b):
    event = Event()
    producer.attach("carState", event)
    rec.received(sm(), [event])
    assert receipt(rec)["qualified"]
  revived = Event()
  a.attach("carState", revived)
  rec.received(sm(), [revived])
  assert not receipt(rec)["qualified"]
  assert any("retired upstream epoch" in error for error in rec.errors)


def test_all_receive_updates_and_exact_consumer_clock_retained():
  rec = Recorder("planner")
  master = sm("carControl")
  master.recv_time = {"carControl": 10.125}
  master.alive = master.valid = master.freq_ok = {"carControl": True}
  rec.received(master, [Event("carControl")], 10.125)
  master.frame += 1
  master.updated["carControl"] = False
  master.alive = {"carControl": False}
  rec.received(master, [None], 11.25)
  rec.begin(master)
  out = receipt(rec)
  assert [update["cur_time"] for update in out["receive_updates"]] == [10.125, 11.25]
  assert [update["frame"] for update in out["receive_updates"]] == [2, 3]
  assert out["receive_updates"][1]["received"] == [None]
  assert out["receive_updates"][0]["resulting_health"]["carControl"]["alive"]
  assert out["inputs"]["carControl"]["alive"] is False
  assert out["inputs"]["carControl"]["receive_time"] == 10.125
  master.frame += 1
  rec.received(master, [], 11.5)
  rec.begin()
  assert [update["cur_time"] for update in receipt(rec)["receive_updates"]] == [11.5]


def test_begin_never_serializes_pending_tail_and_faults_do_not_escape():
  rec = Recorder("card")
  receipt(rec)
  rec.can_batch([], "CI.init")
  with patch("openpilot.common.producer_consumption.canonical", side_effect=ValueError("bad serialization")):
    rec.begin()
  assert rec.pending_can[0]["phase"] == "CI.init"
  with patch.object(rec, "_begin", side_effect=ValueError("injected diagnostic failure")):
    rec.begin()
  assert not receipt(rec)["qualified"]


def test_wrong_required_upstream_producer_rejected():
  event = Event("radarState")
  Recorder("card").attach("radarState", event)
  rec = Recorder("planner")
  rec.received(sm("radarState"), [event])
  assert not receipt(rec)["qualified"]


def test_default_input_explicit_and_receive_queue_bound_fail_closed():
  rec = Recorder("planner", max_bytes=2000)
  master = sm("carControl", seen=False, updated=False)
  master.data = {"carControl": Event("carControl", enabled=False)}
  rec.received(master, [], 1.0)
  out = receipt(rec)
  assert out["inputs"]["carControl"]["instance"] is None
  assert out["inputs"]["carControl"]["initial_default"]["carControl"]["enabled"] is False
  rec.begin()
  for i in range(20):
    rec.received(master, [], i + 2.0)
  assert not receipt(rec)["qualified"]


def test_uuid_failure_cannot_interrupt_process_initialization():
  with patch("openpilot.common.producer_consumption.uuid.uuid4", side_effect=OSError("entropy unavailable")):
    rec = Recorder("card")
  assert rec.epoch == ""
  out = receipt(rec)
  assert not out["qualified"] and "initialization epoch" in out["errors"][0]


def test_real_list_service_initial_default_is_available():
  rec = Recorder("card", epoch="test")
  master = sm("onroadEvents", seen=False, updated=False)
  master.data = {"onroadEvents": messaging.new_message("onroadEvents", 0).as_reader().onroadEvents}
  result = receipt(rec, "carState", master)
  assert result["qualified"]
  assert result["inputs"]["onroadEvents"]["initial_default"] == []


def test_reset_bookkeeping_fault_is_diagnostic_only():
  rec = Recorder("radard")
  with patch.object(rec, "note", side_effect=ValueError("injected reset error")):
    rec.reset("lead0")
  assert not receipt(rec)["qualified"]
