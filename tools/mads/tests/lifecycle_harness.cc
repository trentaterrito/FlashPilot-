#include <cassert>
#include "openpilot/selfdrive/pandad/mads_lifecycle.h"
int main() {
  assert(mads_state_period(false) == 10U);
  assert(mads_state_period(true) == 10U);
  assert(!mads_host_fresh(true, 0, 0));
  assert(!mads_host_fresh(false, 10, 10));
  assert(!mads_host_fresh(true, 9, 10));
  assert(mads_host_fresh(true, 100000010, 10));
  assert(mads_host_fresh(true, 100000011, 10));
  for (uint64_t n = 1; n < 100; n++) {
    const uint64_t sent = n * 20000000;
    assert(mads_host_fresh(true, sent + 20000000, sent));
    assert(mads_host_fresh(true, sent + 100000001, sent));
    assert(!mads_host_fresh(false, sent + 100000001, sent));
  }
}
