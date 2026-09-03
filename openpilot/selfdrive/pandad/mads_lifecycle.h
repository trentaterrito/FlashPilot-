#pragma once
#include <cstdint>

// Scheduling only. No extension of panda's 100 ms eligibility deadline.
constexpr unsigned int mads_state_period(bool selected) {
  return selected ? 2U : 10U;  // pandad 100 Hz: 50 Hz selected, legacy 10 Hz OFF
}

constexpr bool mads_host_fresh(bool sources_valid, uint64_t now, uint64_t sent) {
  return sources_valid && (sent != 0U) && (now >= sent) && ((now - sent) <= 100000000ULL);
}
