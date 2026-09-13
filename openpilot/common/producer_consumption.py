"""Passive producer receipts. Never use these fields as control inputs.

The receipt identifies actual receives, not a reconstruction of scheduling. A
diagnostic error poisons this process epoch for qualification, not for driving.
"""
import hashlib
import json
import math
import struct
import uuid

from openpilot.cereal import log, messaging


def _normalized(value):
  if isinstance(value, float) and not math.isfinite(value):
    return {"float64_bits": struct.pack(">d", value).hex()}
  if isinstance(value, bytes):
    return {"bytes_hex": value.hex()}
  if isinstance(value, dict):
    return {str(k): _normalized(v) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [_normalized(v) for v in value]
  return value


def canonical(value):
  return json.dumps(_normalized(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
  return hashlib.sha256(canonical(value).encode()).hexdigest()


class Recorder:
  def __init__(self, producer, *, epoch=None, max_bytes=65536):
    self.producer = producer
    self.errors = []
    try:
      self.epoch = epoch or uuid.uuid4().hex
    except Exception as exc:
      self.epoch = ""
      self.fail(f"initialization epoch:{type(exc).__name__}:{exc}")
    self.max_bytes = max_bytes
    self.step = 0
    self.publication = 0
    self.phase = "initialization"
    self.inputs = {}
    self.receive_ordinals = {}
    self.receive_chain = ""
    self.receipt_chain = ""
    self.pending_can = []
    self.can_sequence = 0
    self.state = {}
    self.sm = None
    self._pending_bytes = 0
    self.notes = []
    self.reset_epochs = {}
    self.published_step = False
    self.upstream_instances = {}
    self.upstream_epochs = {}
    self.retired_upstream_epochs = set()
    self._published_can_count = 0
    self._published_note_count = 0
    self.pending_receive_updates = []
    self._published_receive_count = 0
    self._can_sizes = []
    self._receive_sizes = []

  def fail(self, reason):
    # Bounded, sticky error evidence; never clear an error on the next update.
    reason = str(reason)[:256]
    if reason not in self.errors and len(self.errors) < 8:
      self.errors.append(reason)

  def begin(self, sm=None, phase="update"):
    try:
      self._begin(sm, phase)
    except Exception as exc:
      self.fail(f"begin:{type(exc).__name__}:{exc}")

  def _begin(self, sm, phase):
    self.step += 1
    self.phase = phase
    self.sm = sm if sm is not None else self.sm
    self.state = {k: v for k, v in self.state.items() if k == "initial" and not self.published_step}
    if self.published_step:
      # Initialization/control callbacks can run after this step's selected
      # publications. Retain evidence added after the last successful attach.
      self.pending_can = self.pending_can[self._published_can_count:]
      self._can_sizes = self._can_sizes[self._published_can_count:]
      self._pending_bytes = sum(self._can_sizes)
      self.notes = self.notes[self._published_note_count:]
      self.pending_receive_updates = self.pending_receive_updates[self._published_receive_count:]
      self._receive_sizes = self._receive_sizes[self._published_receive_count:]
    self._published_can_count = 0
    self._published_note_count = 0
    self._published_receive_count = 0
    self.published_step = False

  def note(self, label, value):
    try:
      item = {"label": label, "step": self.step, "value": json.loads(canonical(value))}
      if sum(len(canonical(x)) for x in self.notes) + len(canonical(item)) > self.max_bytes:
        raise ValueError("notes exceed receipt bound")
      self.notes.append(item)
    except Exception as exc:
      self.fail(f"note:{label}:{type(exc).__name__}:{exc}")

  def reset(self, label):
    try:
      self.reset_epochs[label] = self.reset_epochs.get(label, 0) + 1
      self.note("reset", {"component": label, "epoch": self.reset_epochs[label]})
    except Exception as exc:
      self.fail(f"reset:{type(exc).__name__}:{exc}")

  def capture_state(self, label, callback):
    try:
      value = callback()
      # State snapshots are assertions about numeric history, unlike arbitrary
      # input-message hashes, which must also represent diagnostic NaN fields.
      json.dumps(value, allow_nan=False)
      snapshot = json.loads(canonical(value))
      if len(canonical(snapshot)) > self.max_bytes:
        raise ValueError("state exceeds receipt bound")
      self.state[label] = snapshot
    except Exception as exc:
      self.state[label] = {"unavailable": True}
      self.fail(f"state:{label}:{type(exc).__name__}:{exc}")

  @staticmethod
  def _health(sm, name):
    return {"seen": bool(sm.seen[name]), "updated": bool(sm.updated[name]),
            "receive_frame": int(sm.recv_frame[name]), "log_mono_ns": int(sm.logMonoTime[name]),
            "receive_time": getattr(sm, "recv_time", {}).get(name),
            "alive": getattr(sm, "alive", {}).get(name), "valid": getattr(sm, "valid", {}).get(name),
            "freq_ok": getattr(sm, "freq_ok", {}).get(name)}

  def received(self, sm, msgs, cur_time=None):
    self.sm = sm
    ordered = []
    for msg in msgs:
      if msg is None:
        ordered.append(None)
        continue
      service = "unknown"
      try:
        service = msg.which()
        ordinal = self.receive_ordinals.get(service, 0) + 1
        self.receive_ordinals[service] = ordinal
        # Remove previous binding before decoding; failure cannot reuse it.
        self.inputs[service] = {"unavailable": True, "receive_ordinal": ordinal}
        upstream_text = str(getattr(msg, "producerConsumption", ""))
        upstream = json.loads(upstream_text) if upstream_text else None
        publisher = None
        if upstream is not None:
          if (upstream.get("version") != 1 or not upstream.get("qualified") or
              upstream.get("service") != service or upstream.get("publication_mono_ns") != int(msg.logMonoTime)):
            raise ValueError("invalid upstream receipt")
          publisher = {k: upstream[k] for k in ("producer", "epoch", "step", "publication", "receipt_sha256")}
          expected_producer = {"carState": "card", "radarTracks": "card", "radarState": "radard"}.get(service)
          if expected_producer is not None and publisher["producer"] != expected_producer:
            raise ValueError("wrong upstream producer for service")
          unsigned = {k: v for k, v in upstream.items() if k != "receipt_sha256"}
          if not publisher["epoch"] or publisher["publication"] < 1 or digest(unsigned) != publisher["receipt_sha256"]:
            raise ValueError("upstream receipt identity/hash invalid")
          # Different service sockets may legitimately arrive out of publisher
          # order. Check monotonicity only on one actual service stream.
          key = (service, publisher["producer"], publisher["epoch"])
          stream = (service, publisher["producer"])
          old_epoch = self.upstream_epochs.get(stream)
          if key in self.retired_upstream_epochs:
            raise ValueError("retired upstream epoch revived")
          if old_epoch is not None and old_epoch != publisher["epoch"]:
            self.retired_upstream_epochs.add((*stream, old_epoch))
          self.upstream_epochs[stream] = publisher["epoch"]
          previous = self.upstream_instances.get(key)
          current = (publisher["publication"], publisher["receipt_sha256"])
          if previous is not None and (current[0] < previous[0] or (current[0] == previous[0] and current[1] != previous[1])):
            raise ValueError("upstream publication reversal/fork")
          self.upstream_instances[key] = current
        elif service in ("carState", "radarTracks", "radarState"):
          raise ValueError("required upstream producer receipt missing")
        item = {"receive_ordinal": ordinal, "receive_frame": sm.frame,
                "log_mono_ns": int(msg.logMonoTime), "valid": bool(msg.valid),
                "content_sha256": digest(msg.to_dict()), "content_encoding": "decoded-event-json-v1",
                "publisher": publisher, "publisher_sequence_available": publisher is not None,
                "model_runtime_ref": str(getattr(msg, "modelRuntimeRef", ""))}
        self.inputs[service] = item
        self.receive_chain = digest([self.receive_chain, service, item])
      except Exception as exc:
        self.fail(f"receive:{service}:{type(exc).__name__}:{exc}")
      ordered.append({"service": service, "instance": self.inputs.get(service, {"unavailable": True})})
    try:
      batch = {"frame": sm.frame, "cur_time": cur_time, "received": ordered,
               "resulting_health": {name: self._health(sm, name) for name in sm.services}}
      size = len(canonical(batch))
      if sum(self._receive_sizes) + size > self.max_bytes:
        raise ValueError("pending receive updates exceed receipt bound")
      self.pending_receive_updates.append(batch)
      self._receive_sizes.append(size)
    except Exception as exc:
      self.fail(f"receive update:{type(exc).__name__}:{exc}")

  def can_batch(self, events, phase="update"):
    self.can_sequence += 1
    try:
      identities = []
      for event in events:
        if isinstance(event, bytes):
          with log.Event.from_bytes(event) as decoded:
            identities.append(self._can_identity(decoded, hashlib.sha256(event).hexdigest()))
        else:
          identities.append(self._can_identity(event, None))
      batch = {"sequence": self.can_sequence, "step": self.step, "phase": phase,
               "events": identities, "event_count": len(identities), "sha256": digest(identities)}
      size = len(canonical(batch))
      if self._pending_bytes + size > self.max_bytes:
        raise ValueError("pending CAN evidence exceeds receipt bound")
      self.pending_can.append(batch)
      self._can_sizes.append(size)
      self._pending_bytes += size
    except Exception as exc:
      self.fail(f"can:{self.can_sequence}:{type(exc).__name__}:{exc}")

  @staticmethod
  def _can_identity(event, raw_hash):
    if event.which() != "can":
      raise ValueError("not a CAN Event")
    # to_dict includes every declared frame field, including busTime. The raw
    # frame payload remains in the ordinary rlog; receipts do not duplicate it.
    return {"log_mono_ns": int(event.logMonoTime), "frame_count": len(event.can),
            "content_sha256": digest(event.to_dict()), "wire_sha256": raw_hash,
            "content_encoding": "decoded-event-json-v1"}

  def attach(self, service, msg, sm=None):
    self.publication += 1
    try:
      sm = sm if sm is not None else self.sm
      inputs = {}
      if sm is not None:
        for name in sm.services:
          inputs[name] = {"instance": self.inputs.get(name), **self._health(sm, name)}
          if not sm.seen[name]:
            default = getattr(sm, "data", {}).get(name)
            if default is None:
              initial = None
            elif hasattr(default, "to_dict"):
              initial = default.to_dict()
            else:
              # SubMaster also initializes list-valued services (pandaStates,
              # onroadEvents). An empty list is a real default, not a fault.
              initial = [v.to_dict() if hasattr(v, "to_dict") else v for v in default]
            inputs[name]["initial_default"] = _normalized(initial)
          if sm.seen[name] and name not in self.inputs:
            self.fail(f"missing input binding:{name}")
      receipt = {"version": 1, "producer": self.producer, "epoch": self.epoch,
                 "initialization_epoch": self.epoch, "step": self.step, "phase": self.phase,
                 "publication": self.publication, "service": service,
                 "publication_mono_ns": int(msg.logMonoTime), "sm_frame": None if sm is None else sm.frame,
                 "inputs": inputs, "can_batches": self.pending_can, "state": self.state,
                 "notes": self.notes, "reset_epochs": self.reset_epochs,
                 "receive_updates": self.pending_receive_updates,
                 "receive_chain_sha256": self.receive_chain, "previous_receipt_sha256": self.receipt_chain,
                 "qualified": not self.errors, "errors": list(self.errors)}
      encoded = canonical(receipt)
      if len(encoded.encode()) > self.max_bytes - 128:
        self.fail("publication receipt exceeds bound; evidence unavailable")
        receipt = {k: receipt[k] for k in ("version", "producer", "epoch", "step", "publication", "service", "publication_mono_ns")}
        receipt.update(qualified=False, errors=list(self.errors), previous_receipt_sha256=self.receipt_chain)
      receipt["receipt_sha256"] = digest(receipt)
      msg.producerConsumption = canonical(receipt)
      self.receipt_chain = receipt["receipt_sha256"]
      self.published_step = True
      self._published_can_count = len(self.pending_can)
      self._published_note_count = len(self.notes)
      self._published_receive_count = len(self.pending_receive_updates)
    except Exception as exc:
      self.fail(f"attach:{type(exc).__name__}:{exc}")
      # Missing/empty receipt is unqualified. Do not propagate diagnostics into
      # a control-publication failure, including when an old schema is loaded.
      try:
        msg.producerConsumption = ""
      except Exception:
        pass


class ObservedSubMaster(messaging.SubMaster):
  def __init__(self, *args, recorder, **kwargs):
    self.recorder = recorder
    super().__init__(*args, **kwargs)

  def update_msgs(self, cur_time, msgs):
    super().update_msgs(cur_time, msgs)
    try:
      self.recorder.received(self, msgs, cur_time)
    except Exception as exc:
      self.recorder.fail(f"receive callback:{type(exc).__name__}:{exc}")


class ObservedPubMaster(messaging.PubMaster):
  def __init__(self, *args, recorder, observed, **kwargs):
    self.recorder = recorder
    self.observed = frozenset(observed)
    self.sm = None
    super().__init__(*args, **kwargs)

  def send(self, service, msg):
    if service in self.observed:
      try:
        self.recorder.attach(service, msg, self.sm)
      except Exception as exc:
        self.recorder.fail(f"publish callback:{type(exc).__name__}:{exc}")
        try:
          msg.producerConsumption = ""
        except Exception:
          pass
    return super().send(service, msg)
