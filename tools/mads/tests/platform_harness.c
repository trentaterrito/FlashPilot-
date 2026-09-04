// Actual board fault predicate with simulated registers; not hardware validation.
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "board/health.h"
#define PANDA_CAN_CNT 3
#define HARNESS_STATUS_NC 0
static unsigned int critical_depth;
#define ENTER_CRITICAL() (++critical_depth)
#define EXIT_CRITICAL() (--critical_depth)
static uint32_t faults, rx_buffer_overflow, tx_buffer_overflow;
static uint16_t spi_error_count;
static bool power_save_enabled, heartbeat_lost, heartbeat_disabled;
static bool heartbeat_engaged_mads, ignition_can, ignition_gpio;
static struct { bool sbu_adc_lock; int status; } harness;
static can_health_t can_health[PANDA_CAN_CNT];
static unsigned int gpio_reads;
static bool harness_check_ignition(void) {
  assert(!harness.sbu_adc_lock && critical_depth > 0U);
  gpio_reads++;
  return ignition_gpio;
}
#include "board/flashpilot_mads_platform.h"

void platform_reset(void) {
  faults = rx_buffer_overflow = tx_buffer_overflow = 0U;
  spi_error_count = 0U;
  power_save_enabled = heartbeat_lost = heartbeat_disabled = false;
  heartbeat_engaged_mads = ignition_can = true;
  ignition_gpio = false;
  harness.sbu_adc_lock = false;
  harness.status = 1;
  memset(can_health, 0, sizeof(can_health));
  (void)flashpilot_mads_platform_ready(); // observe reset counters, never a grant
  assert(flashpilot_mads_platform_ready());
  gpio_reads = 0U;
}

bool platform_ready(void) {
  bool result = flashpilot_mads_platform_ready();
  assert(critical_depth == 0U);
  return result;
}

unsigned int platform_gpio_reads(void) { return gpio_reads; }

void platform_fault(int kind, int bus) {
  assert(bus >= 0 && bus < PANDA_CAN_CNT);
  switch (kind) {
    case 0: faults = 1U; break;
    case 1: power_save_enabled = true; break;
    case 2: heartbeat_lost = true; break;
    case 3: heartbeat_disabled = true; break;
    case 4: heartbeat_engaged_mads = false; break;
    case 5: harness.sbu_adc_lock = true; break;
    case 6: harness.status = HARNESS_STATUS_NC; break;
    case 7: ignition_can = false; break;
    case 8: rx_buffer_overflow++; break;
    case 9: tx_buffer_overflow++; break;
    case 10: spi_error_count++; break;
    case 11: can_health[bus].bus_off = 1U; break;
    case 12: can_health[bus].error_passive = 1U; break;
    case 13: can_health[bus].total_error_cnt++; break;
    case 14: can_health[bus].total_tx_checksum_error_cnt++; break;
    case 15: can_health[bus].can_core_reset_cnt++; break;
    case 16: can_health[bus].total_rx_lost_cnt++; break;
    case 17: can_health[bus].total_tx_lost_cnt++; break;
    default: assert(false); break;
  }
}
