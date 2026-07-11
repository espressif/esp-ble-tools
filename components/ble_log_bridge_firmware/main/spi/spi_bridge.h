#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
    uint64_t spi_received_bytes;
    uint64_t usb_queued_bytes;
    uint64_t locally_dropped_bytes;
    uint64_t rx_starvation_duration_us;
    uint32_t completed_transactions;
    uint32_t zero_length_transactions;
    uint32_t non_byte_transactions;
    uint32_t aborted_transactions;
    uint32_t spi_dma_errors;
    uint32_t rx_starvation_count;
    uint16_t cdc_fifo_used;
    uint16_t cdc_fifo_peak;
    uint16_t available_rx_transactions;
    uint32_t event_flags;
} spi_bridge_statistics_t;

enum {
    SPI_BRIDGE_EVENT_CDC_PRESSURE = 1U << 0,
    SPI_BRIDGE_EVENT_DMA_PRESSURE = 1U << 1,
    SPI_BRIDGE_EVENT_RX_STARVATION = 1U << 2,
    SPI_BRIDGE_EVENT_SPI_ERROR = 1U << 3,
};

esp_err_t spi_bridge_init(void);
esp_err_t spi_bridge_start(void);
esp_err_t spi_bridge_stop(void);
void spi_bridge_on_usb_disconnect(void);
void spi_bridge_get_statistics(spi_bridge_statistics_t *statistics);
uint64_t spi_bridge_finish_stop(uint32_t timeout_ms);
