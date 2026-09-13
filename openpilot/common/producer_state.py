"""Read-only state snapshots and actual reset notifications for producer receipts.

No value in this module is used to select or compute a control output. Snapshots
are not restoration checkpoints: replay still starts from recorded initialization
and consumes the exact ordered inputs. In particular, opaque CAN parser/solver
state is never guessed from a publication.
"""
import functools
import weakref

_reset_observers = weakref.WeakKeyDictionary()


def watch_resets(obj, recorder, component):
  try:
    _reset_observers[obj] = (recorder, component)
  except Exception as exc:
    recorder.fail(f"reset registration:{type(exc).__name__}:{exc}")


def note_reset(obj, reason):
  """Called at an existing reset, not from a duplicated reset predicate."""
  try:
    observer = _reset_observers.get(obj)
    if observer is not None:
      recorder, component = observer
      recorder.reset(f"{component}:{reason}")
  except Exception:
    # Missing diagnostic evidence cannot interrupt a control reset. The
    # recorder itself latches failures while creating the receipt.
    if 'observer' in locals() and observer is not None:
      observer[0].fail("reset notification unavailable")


def observe_cruise_arguments(car, recorder):
  """Observe the actual arguments, including asynchronously updated Params.

  Reading car.is_metric/experimental_mode again after the call is not evidence
  of which value the call consumed. These wrappers return the original result
  and pass the original arguments, without consulting diagnostic state.
  """
  def wrap(method, label):
    @functools.wraps(method)
    def observed(*args, **kwargs):
      try:
        # Calls in card are positional; retain keyword calls without guessing.
        recorder.note(label, {"arguments_after_CS": list(args[1:]), "keywords": kwargs})
      except Exception as exc:
        recorder.fail(f"cruise argument receipt:{type(exc).__name__}:{exc}")
      return method(*args, **kwargs)
    return observed
  car.v_cruise_helper.update_v_cruise = wrap(car.v_cruise_helper.update_v_cruise, "cruise.update")
  car.v_cruise_helper.initialize_v_cruise = wrap(car.v_cruise_helper.initialize_v_cruise, "cruise.initialize")


def _filter(f):
  return {"x": float(f.x), "alpha": float(f.alpha), "dt": float(f.dt), "initialized": bool(f.initialized)}


def radar_state(rd):
  return {
    "ready": rd.ready, "last_v_ego_frame": rd.last_v_ego_frame, "v_ego": rd.v_ego,
    "v_ego_history": list(rd.v_ego_hist), "v_ego_history_capacity": rd.v_ego_hist.maxlen,
    "lead_probability": [_filter(f) for f in rd.lead_prob_filters],
    "conditioned_vrel": [f.x for f in rd.vrel_filters],
    "trust": [{"score": s.score, "previous_d_rel": s.prev_d_rel} for s in rd.trust_states],
    "ttc": [{"previous_ttc": s.prev_ttc, "previous_was_sentinel": s.prev_was_sentinel,
             "derivative_filter": _filter(s.deriv_filter)} for s in rd.ttc_states],
    "anticipation_cap": list(rd.anticipation_cap),
    "tracks": [{"id": key, "updates": t.cnt, "kf_x": [[float(v) for v in row] for row in t.kf.x],
                "acceleration_tau": _filter(t.aLeadTau)} for key, t in sorted(rd.tracks.items())],
    "ford_shadow": None if rd.ford_observability is None else dict(vars(rd.ford_observability)),
  }


def planner_state(planner):
  return {"v_desired_filter": _filter(planner.v_desired_filter), "a_cruise": float(planner.a_cruise),
          "output_a_target": float(planner.output_a_target), "output_should_stop": bool(planner.output_should_stop),
          "mpc_state": "opaque: replay from initialization; not a solver checkpoint"}


def card_state(card):
  cruise = card.v_cruise_helper
  radar = card.RI
  return {
    "CI": f"{type(card.CI).__module__}.{type(card.CI).__qualname__}",
    "RI": f"{type(radar).__module__}.{type(radar).__qualname__}",
    "initialized_previous": card.initialized_prev,
    "previous_control_enabled": bool(card.CC_prev.enabled),
    "previous_car_state_v_ego": float(card.CS_prev.vEgo),
    "cruise": {"v": float(cruise.v_cruise_kph), "cluster": float(cruise.v_cruise_cluster_kph),
               "last": float(cruise.v_cruise_kph_last), "button_timers": dict(cruise.button_timers),
               "button_change_states": dict(cruise.button_change_states)},
    "radar_relative_velocity_history": list(getattr(radar, "v_rel_history", [])),
    "radar_relative_velocity_capacity": getattr(getattr(radar, "v_rel_history", None), "maxlen", None),
    "radar_track_id": getattr(radar, "track_id", None),
    "parser_state": "opaque: replay from constructor and ordered CAN batches; not a parser checkpoint",
  }
