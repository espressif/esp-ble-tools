#include "bridge_control.h"

#include <stdatomic.h>
#include <string.h>

#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "tusb.h"

#include "spi_bridge.h"

typedef struct {
    uint8_t sequence;
    uint8_t command;
} queued_command_t;

static QueueHandle_t s_command_queue;
static _Atomic bridge_state_t s_state = BRIDGE_STATE_PAUSED;
static uint32_t s_capture_id;
static bool s_have_cached_response;
static bridge_response_report_t s_cached_response;
static bridge_response_report_t s_pending_response;
static bool s_response_pending;
static bool s_reboot_after_response;
static uint32_t s_last_event_flags;
static uint32_t s_last_event_spi_errors;
static uint64_t s_last_event_dropped_bytes;
static uint32_t s_last_event_starvation_count;
static atomic_bool s_disconnect_pending;

static uint32_t uptime_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static bridge_state_t get_state_locked(void)
{
    return atomic_load(&s_state);
}

static void set_state(bridge_state_t state)
{
    atomic_store(&s_state, state);
}

static bool transition_state(bridge_state_t expected, bridge_state_t next)
{
    return atomic_compare_exchange_strong(&s_state, &expected, next);
}

static bridge_usb_speed_t usb_speed(void)
{
    if (!tud_mounted()) {
        return BRIDGE_USB_SPEED_UNKNOWN;
    }
    return tud_speed_get() == TUSB_SPEED_HIGH ? BRIDGE_USB_SPEED_HIGH : BRIDGE_USB_SPEED_FULL;
}

static bridge_response_report_t make_response(const queued_command_t *command, bridge_result_t result)
{
    return (bridge_response_report_t) {
        .sequence = command->sequence,
        .command = command->command,
        .result = result,
        .state = get_state_locked(),
        .mode = BRIDGE_MODE_SPI_SLAVE,
        .usb_speed = usb_speed(),
        .capture_id = s_capture_id,
        .uptime_ms = uptime_ms(),
    };
}

static void schedule_response(bridge_response_report_t response, bool cache)
{
    s_pending_response = response;
    s_response_pending = true;
    if (cache) {
        s_cached_response = response;
        s_have_cached_response = true;
    }
}

static void handle_capture(const queued_command_t *command)
{
    if (get_state_locked() != BRIDGE_STATE_PAUSED) {
        schedule_response(make_response(command, BRIDGE_RESULT_INVALID_STATE), true);
        return;
    }
    if (usb_speed() != BRIDGE_USB_SPEED_HIGH) {
        schedule_response(make_response(command, BRIDGE_RESULT_UNSUPPORTED_USB_SPEED), true);
        return;
    }
    if (!transition_state(BRIDGE_STATE_PAUSED, BRIDGE_STATE_CAPTURING)) {
        schedule_response(make_response(command, BRIDGE_RESULT_INVALID_STATE), true);
        return;
    }
    if (spi_bridge_start() != ESP_OK) {
        set_state(BRIDGE_STATE_ERROR);
        schedule_response(make_response(command, BRIDGE_RESULT_INTERNAL_ERROR), true);
        return;
    }

    ++s_capture_id;
    if (s_capture_id == 0) {
        ++s_capture_id;
    }
    s_last_event_flags = 0;
    s_last_event_spi_errors = 0;
    s_last_event_dropped_bytes = 0;
    s_last_event_starvation_count = 0;
    schedule_response(make_response(command, BRIDGE_RESULT_OK), true);
}

static void handle_stop(const queued_command_t *command)
{
    if (!transition_state(BRIDGE_STATE_CAPTURING, BRIDGE_STATE_PAUSING)) {
        schedule_response(make_response(command, BRIDGE_RESULT_INVALID_STATE), true);
        return;
    }

    if (spi_bridge_stop() != ESP_OK) {
        set_state(BRIDGE_STATE_ERROR);
        schedule_response(make_response(command, BRIDGE_RESULT_INTERNAL_ERROR), true);
        return;
    }

    spi_bridge_statistics_t statistics;
    spi_bridge_get_statistics(&statistics);
    const uint64_t discarded = spi_bridge_finish_stop(CONFIG_BRIDGE_STOP_DRAIN_TIMEOUT_MS);
    set_state(BRIDGE_STATE_PAUSED);
    bridge_response_report_t response = make_response(command, BRIDGE_RESULT_OK);
    response.stop_discarded_bytes = discarded;
    response.expected_host_bytes = statistics.usb_queued_bytes - discarded;
    response.locally_dropped_bytes = statistics.locally_dropped_bytes;
    schedule_response(response, true);
}

static void handle_command(const queued_command_t *command)
{
    if (s_have_cached_response && command->sequence == s_cached_response.sequence) {
        if (command->command == s_cached_response.command) {
            schedule_response(s_cached_response, false);
        } else {
            schedule_response(make_response(command, BRIDGE_RESULT_SEQUENCE_CONFLICT), false);
        }
        return;
    }

    switch (command->command) {
    case BRIDGE_COMMAND_CAPTURE:
        handle_capture(command);
        break;
    case BRIDGE_COMMAND_STOP:
        handle_stop(command);
        break;
    case BRIDGE_COMMAND_GET_STATUS:
        schedule_response(make_response(command, BRIDGE_RESULT_OK), true);
        break;
    case BRIDGE_COMMAND_REBOOT:
        if (get_state_locked() != BRIDGE_STATE_PAUSED) {
            schedule_response(make_response(command, BRIDGE_RESULT_INVALID_STATE), true);
        } else {
            schedule_response(make_response(command, BRIDGE_RESULT_OK), true);
            s_reboot_after_response = true;
        }
        break;
    default:
        schedule_response(make_response(command, BRIDGE_RESULT_INTERNAL_ERROR), true);
        break;
    }
}

static bool send_response(void)
{
    if (!s_response_pending || !tud_hid_n_ready(0)) {
        return false;
    }
    if (!tud_hid_n_report(0, BRIDGE_REPORT_RESPONSE, &s_pending_response, sizeof(s_pending_response))) {
        return false;
    }
    s_response_pending = false;
    if (s_reboot_after_response) {
        s_reboot_after_response = false;
        vTaskDelay(pdMS_TO_TICKS(100));
        esp_restart();
    }
    return true;
}

static bool send_capture_event(void)
{
    if (get_state_locked() != BRIDGE_STATE_CAPTURING || !tud_hid_n_ready(0)) {
        return false;
    }
    spi_bridge_statistics_t statistics;
    spi_bridge_get_statistics(&statistics);
    if (statistics.event_flags == s_last_event_flags &&
        statistics.spi_dma_errors == s_last_event_spi_errors &&
        statistics.locally_dropped_bytes == s_last_event_dropped_bytes &&
        statistics.rx_starvation_count == s_last_event_starvation_count) {
        return false;
    }
    s_last_event_flags = statistics.event_flags;
    s_last_event_spi_errors = statistics.spi_dma_errors;
    s_last_event_dropped_bytes = statistics.locally_dropped_bytes;
    s_last_event_starvation_count = statistics.rx_starvation_count;
    const bridge_capture_event_report_t report = {
        .capture_id = s_capture_id,
        .flags = statistics.event_flags,
        .cdc_fifo_used = statistics.cdc_fifo_used,
        .cdc_fifo_peak = statistics.cdc_fifo_peak,
        .available_rx_transactions = statistics.available_rx_transactions,
        .spi_dma_errors = statistics.spi_dma_errors,
        .locally_dropped_bytes = statistics.locally_dropped_bytes,
        .rx_starvation_count = statistics.rx_starvation_count,
        .rx_starvation_duration_us = statistics.rx_starvation_duration_us,
    };
    return tud_hid_n_report(0, BRIDGE_REPORT_CAPTURE_EVENT, &report, sizeof(report));
}

static bool send_heartbeat(void)
{
    if (!tud_hid_n_ready(0)) {
        return false;
    }
    const bridge_heartbeat_report_t report = {
        .state = get_state_locked(),
        .mode = BRIDGE_MODE_SPI_SLAVE,
        .usb_speed = usb_speed(),
        .capture_id = s_capture_id,
        .uptime_ms = uptime_ms(),
    };
    return tud_hid_n_report(0, BRIDGE_REPORT_HEARTBEAT, &report, sizeof(report));
}

static bool send_statistics(void)
{
    if (get_state_locked() != BRIDGE_STATE_CAPTURING || !tud_hid_n_ready(0)) {
        return false;
    }
    spi_bridge_statistics_t statistics;
    spi_bridge_get_statistics(&statistics);
    const bridge_capture_statistics_report_t report = {
        .capture_id = s_capture_id,
        .spi_received_bytes = statistics.spi_received_bytes,
        .usb_queued_bytes = statistics.usb_queued_bytes,
        .locally_dropped_bytes = statistics.locally_dropped_bytes,
        .completed_transactions = statistics.completed_transactions,
        .zero_length_transactions = statistics.zero_length_transactions,
        .non_byte_transactions = statistics.non_byte_transactions,
        .aborted_transactions = statistics.aborted_transactions,
        .spi_dma_errors = statistics.spi_dma_errors,
        .rx_starvation_count = statistics.rx_starvation_count,
        .rx_starvation_duration_us = statistics.rx_starvation_duration_us,
        .cdc_fifo_used_percent = statistics.cdc_fifo_used * 100U / CONFIG_TINYUSB_CDC_TX_BUFSIZE,
        .cdc_fifo_peak_percent = statistics.cdc_fifo_peak * 100U / CONFIG_TINYUSB_CDC_TX_BUFSIZE,
    };
    return tud_hid_n_report(0, BRIDGE_REPORT_CAPTURE_STATISTICS, &report, sizeof(report));
}

static void bridge_control_task(void *argument)
{
    (void)argument;
    TickType_t next_heartbeat = xTaskGetTickCount() + pdMS_TO_TICKS(1000);
    TickType_t next_statistics = next_heartbeat;
    for (;;) {
        if (atomic_exchange(&s_disconnect_pending, false)) {
            spi_bridge_on_usb_disconnect();
            set_state(BRIDGE_STATE_PAUSED);
            xQueueReset(s_command_queue);
            s_response_pending = false;
        }
        queued_command_t command;
        if (xQueueReceive(s_command_queue, &command, pdMS_TO_TICKS(10)) == pdTRUE) {
            handle_command(&command);
        }
        if (send_response() || send_capture_event()) {
            continue;
        }
        const TickType_t now = xTaskGetTickCount();
        if (now >= next_heartbeat) {
            if (send_heartbeat()) {
                next_heartbeat = now + pdMS_TO_TICKS(1000);
            }
            continue;
        }
        if (now >= next_statistics) {
            if (send_statistics() || get_state_locked() != BRIDGE_STATE_CAPTURING) {
                next_statistics = now + pdMS_TO_TICKS(1000);
            }
        }
    }
}

esp_err_t bridge_control_init(void)
{
    s_command_queue = xQueueCreate(1, sizeof(queued_command_t));
    if (s_command_queue == NULL) {
        return ESP_ERR_NO_MEM;
    }
    return xTaskCreate(bridge_control_task, "bridge_control", 6144, NULL, 5, NULL) == pdPASS
               ? ESP_OK
               : ESP_ERR_NO_MEM;
}

bool bridge_control_begin_update(void)
{
    return transition_state(BRIDGE_STATE_PAUSED, BRIDGE_STATE_UPDATING);
}

void bridge_control_end_update(void)
{
    set_state(BRIDGE_STATE_PAUSED);
}

void bridge_control_usb_disconnected(void)
{
    atomic_store(&s_disconnect_pending, true);
}

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                               uint8_t *buffer, uint16_t requested_length)
{
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)requested_length;
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                           const uint8_t *buffer, uint16_t buffer_size)
{
    (void)instance;
    (void)report_type;
    if (report_id != BRIDGE_REPORT_COMMAND || buffer_size < sizeof(bridge_command_report_t)) {
        return;
    }
    const bridge_command_report_t *report = (const bridge_command_report_t *)buffer;
    const queued_command_t command = {
        .sequence = report->sequence,
        .command = report->command,
    };
    (void)xQueueSend(s_command_queue, &command, 0);
}
