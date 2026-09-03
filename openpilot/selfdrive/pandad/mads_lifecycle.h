#pragma once
#include <cstdint>

// Reference pandad status/heartbeat cadence; liveness is supplied by SubMaster.
constexpr unsigned int mads_state_period(bool /* selected */) {
  return 10U;  // pandad 100 Hz: 10 Hz status/heartbeat in both modes
}

constexpr bool mads_host_fresh(bool sources_valid, uint64_t now, uint64_t sent) {
  return sources_valid && (sent != 0U) && (now >= sent);
}
