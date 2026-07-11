#pragma once

#include <stdint.h>

typedef enum {
    BRIDGE_STATE_PAUSED = 0,
    BRIDGE_STATE_CAPTURING = 1,
    BRIDGE_STATE_PAUSING = 2,
    BRIDGE_STATE_UPDATING = 3,
    BRIDGE_STATE_ERROR = 4,
} bridge_state_t;

typedef enum {
    BRIDGE_COMMAND_CAPTURE = 1,
    BRIDGE_COMMAND_STOP = 2,
    BRIDGE_COMMAND_GET_STATUS = 3,
    BRIDGE_COMMAND_REBOOT = 4,
} bridge_command_t;

typedef enum {
    BRIDGE_RESULT_OK = 0,
    BRIDGE_RESULT_INVALID_STATE = 1,
    BRIDGE_RESULT_UNSUPPORTED_USB_SPEED = 2,
    BRIDGE_RESULT_SEQUENCE_CONFLICT = 3,
    BRIDGE_RESULT_INTERNAL_ERROR = 4,
} bridge_result_t;

typedef enum {
    BRIDGE_USB_SPEED_UNKNOWN = 0,
    BRIDGE_USB_SPEED_FULL = 1,
    BRIDGE_USB_SPEED_HIGH = 2,
} bridge_usb_speed_t;

enum {
    BRIDGE_REPORT_COMMAND = 1,
    BRIDGE_REPORT_RESPONSE = 2,
    BRIDGE_REPORT_HEARTBEAT = 3,
    BRIDGE_REPORT_CAPTURE_EVENT = 4,
    BRIDGE_REPORT_CAPTURE_STATISTICS = 5,
    BRIDGE_MODE_SPI_SLAVE = 1,
};

typedef struct __attribute__((packed)) {
    uint8_t sequence;
    uint8_t command;
} bridge_command_report_t;

typedef struct __attribute__((packed)) {
    uint8_t sequence;
    uint8_t command;
    uint8_t result;
    uint8_t state;
    uint8_t mode;
    uint8_t usb_speed;
    uint16_t reserved;
    uint32_t capture_id;
    uint32_t uptime_ms;
    uint64_t expected_host_bytes;
    uint64_t stop_discarded_bytes;
    uint64_t locally_dropped_bytes;
} bridge_response_report_t;

typedef struct __attribute__((packed)) {
    uint8_t state;
    uint8_t mode;
    uint8_t usb_speed;
    uint8_t reserved;
    uint32_t capture_id;
    uint32_t uptime_ms;
} bridge_heartbeat_report_t;

typedef struct __attribute__((packed)) {
    uint32_t capture_id;
    uint32_t flags;
    uint16_t cdc_fifo_used;
    uint16_t cdc_fifo_peak;
    uint16_t available_rx_transactions;
    uint16_t reserved;
    uint32_t spi_dma_errors;
    uint64_t locally_dropped_bytes;
    uint64_t rx_starvation_count;
    uint64_t rx_starvation_duration_us;
} bridge_capture_event_report_t;

typedef struct __attribute__((packed)) {
    uint32_t capture_id;
    uint64_t spi_received_bytes;
    uint64_t usb_queued_bytes;
    uint64_t locally_dropped_bytes;
    uint32_t completed_transactions;
    uint32_t zero_length_transactions;
    uint32_t non_byte_transactions;
    uint32_t aborted_transactions;
    uint32_t spi_dma_errors;
    uint32_t rx_starvation_count;
    uint64_t rx_starvation_duration_us;
    uint8_t cdc_fifo_used_percent;
    uint8_t cdc_fifo_peak_percent;
} bridge_capture_statistics_report_t;

_Static_assert(sizeof(bridge_response_report_t) <= 63, "response report exceeds HID packet");
_Static_assert(sizeof(bridge_capture_statistics_report_t) <= 63, "statistics report exceeds HID packet");
