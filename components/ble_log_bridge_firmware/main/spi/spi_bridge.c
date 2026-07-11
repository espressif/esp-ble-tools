#include "spi_bridge.h"

#include <stdatomic.h>
#include <string.h>

#include "driver/spi_slave.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include "tusb.h"

#define SPI_BRIDGE_HOST SPI2_HOST
#define SPI_BRIDGE_MOSI_GPIO 4
#define SPI_BRIDGE_SCLK_GPIO 5
#define SPI_BRIDGE_CS_GPIO 6
#define SPI_BRIDGE_TRANSACTION_COUNT CONFIG_BRIDGE_SPI_QUEUE_DEPTH
#define SPI_BRIDGE_BUFFER_SIZE CONFIG_BRIDGE_SPI_TRANSACTION_SIZE
#define SPI_BRIDGE_CDC_FIFO_SIZE CONFIG_TINYUSB_CDC_TX_BUFSIZE
#define SPI_BRIDGE_CDC_PRESSURE_HIGH ((SPI_BRIDGE_CDC_FIFO_SIZE * 90) / 100)
#define SPI_BRIDGE_CDC_PRESSURE_LOW ((SPI_BRIDGE_CDC_FIFO_SIZE * 70) / 100)
#define SPI_BRIDGE_DMA_PRESSURE_HIGH 12
#define SPI_BRIDGE_DMA_PRESSURE_LOW 38

_Static_assert(SPI_BRIDGE_CDC_FIFO_SIZE <= 0x8000,
               "TinyUSB FIFO depth cannot exceed 32768 bytes");

typedef struct {
    spi_slave_transaction_t transaction;
} receive_slot_t;

static receive_slot_t s_slots[SPI_BRIDGE_TRANSACTION_COUNT];
static spi_slave_transaction_t *s_ready[SPI_BRIDGE_TRANSACTION_COUNT];
static size_t s_ready_head;
static size_t s_ready_count;
static uint16_t s_queued_count;
static bool s_initialized;
static atomic_bool s_capturing;
static bool s_starving;
static int64_t s_starvation_started_us;
static SemaphoreHandle_t s_lock;
static TaskHandle_t s_task;
static spi_bridge_statistics_t s_statistics;

static uint32_t saturating_increment(uint32_t value)
{
    return value == UINT32_MAX ? value : value + 1;
}

static void update_pressure_locked(void)
{
    const uint16_t fifo_used = SPI_BRIDGE_CDC_FIFO_SIZE - tud_cdc_n_write_available(0);
    s_statistics.cdc_fifo_used = fifo_used;
    if (fifo_used > s_statistics.cdc_fifo_peak) {
        s_statistics.cdc_fifo_peak = fifo_used;
    }

    if (fifo_used >= SPI_BRIDGE_CDC_PRESSURE_HIGH) {
        s_statistics.event_flags |= SPI_BRIDGE_EVENT_CDC_PRESSURE;
    } else if (fifo_used <= SPI_BRIDGE_CDC_PRESSURE_LOW) {
        s_statistics.event_flags &= ~SPI_BRIDGE_EVENT_CDC_PRESSURE;
    }

    s_statistics.available_rx_transactions = s_queued_count;
    if (s_queued_count <= SPI_BRIDGE_DMA_PRESSURE_HIGH) {
        s_statistics.event_flags |= SPI_BRIDGE_EVENT_DMA_PRESSURE;
    } else if (s_queued_count >= SPI_BRIDGE_DMA_PRESSURE_LOW) {
        s_statistics.event_flags &= ~SPI_BRIDGE_EVENT_DMA_PRESSURE;
    }

    if (s_queued_count == 0 && !s_starving) {
        s_starving = true;
        s_starvation_started_us = esp_timer_get_time();
        s_statistics.rx_starvation_count = saturating_increment(s_statistics.rx_starvation_count);
        s_statistics.event_flags |= SPI_BRIDGE_EVENT_RX_STARVATION;
    } else if (s_queued_count > 0 && s_starving) {
        s_statistics.rx_starvation_duration_us += esp_timer_get_time() - s_starvation_started_us;
        s_starving = false;
    }
}

static void queue_completed_transactions(void)
{
    spi_slave_transaction_t *transaction;
    while (s_ready_count < SPI_BRIDGE_TRANSACTION_COUNT &&
           spi_slave_get_trans_result(SPI_BRIDGE_HOST, &transaction, 0) == ESP_OK) {
        xSemaphoreTake(s_lock, portMAX_DELAY);
        if (s_queued_count > 0) {
            --s_queued_count;
        }
        s_ready[(s_ready_head + s_ready_count) % SPI_BRIDGE_TRANSACTION_COUNT] = transaction;
        ++s_ready_count;
        s_statistics.completed_transactions = saturating_increment(s_statistics.completed_transactions);
        update_pressure_locked();
        xSemaphoreGive(s_lock);
    }
}

static void discard_ready_transactions(void)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_statistics.aborted_transactions += s_ready_count;
    while (s_ready_count > 0) {
        spi_slave_transaction_t *transaction = s_ready[s_ready_head];
        s_ready_head = (s_ready_head + 1) % SPI_BRIDGE_TRANSACTION_COUNT;
        --s_ready_count;
        if (spi_slave_queue_trans(SPI_BRIDGE_HOST, transaction, 0) == ESP_OK) {
            ++s_queued_count;
        } else {
            s_statistics.spi_dma_errors = saturating_increment(s_statistics.spi_dma_errors);
            s_statistics.event_flags |= SPI_BRIDGE_EVENT_SPI_ERROR;
        }
    }
    s_ready_head = 0;
    xSemaphoreGive(s_lock);
}

static void forward_ready_transaction(void)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (!s_capturing || s_ready_count == 0) {
        xSemaphoreGive(s_lock);
        return;
    }

    spi_slave_transaction_t *transaction = s_ready[s_ready_head];
    const size_t received_bytes = transaction->trans_len / 8;
    if (transaction->trans_len % 8 != 0) {
        s_statistics.non_byte_transactions = saturating_increment(s_statistics.non_byte_transactions);
    }
    if (received_bytes == 0) {
        s_statistics.zero_length_transactions = saturating_increment(s_statistics.zero_length_transactions);
    }

    if (received_bytes > 0 && tud_cdc_n_write_available(0) < received_bytes) {
        update_pressure_locked();
        xSemaphoreGive(s_lock);
        return;
    }

    if (received_bytes > 0) {
        const uint32_t written = tud_cdc_n_write(0, transaction->rx_buffer, received_bytes);
        if (written != received_bytes) {
            s_statistics.locally_dropped_bytes += received_bytes - written;
        }
        s_statistics.spi_received_bytes += received_bytes;
        s_statistics.usb_queued_bytes += written;
        tud_cdc_n_write_flush(0);
    }

    s_ready_head = (s_ready_head + 1) % SPI_BRIDGE_TRANSACTION_COUNT;
    --s_ready_count;
    const esp_err_t result = spi_slave_queue_trans(SPI_BRIDGE_HOST, transaction, 0);
    if (result == ESP_OK) {
        ++s_queued_count;
    } else {
        s_statistics.spi_dma_errors = saturating_increment(s_statistics.spi_dma_errors);
        s_statistics.event_flags |= SPI_BRIDGE_EVENT_SPI_ERROR;
    }
    update_pressure_locked();
    xSemaphoreGive(s_lock);
}

static void spi_bridge_task(void *argument)
{
    (void)argument;
    for (;;) {
        if (s_capturing) {
            queue_completed_transactions();
            forward_ready_transaction();
        }
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(1));
    }
}

esp_err_t spi_bridge_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    if (s_lock == NULL) {
        return ESP_ERR_NO_MEM;
    }

    const spi_bus_config_t bus_config = {
        .mosi_io_num = SPI_BRIDGE_MOSI_GPIO,
        .miso_io_num = -1,
        .sclk_io_num = SPI_BRIDGE_SCLK_GPIO,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = SPI_BRIDGE_BUFFER_SIZE,
    };
    const spi_slave_interface_config_t slave_config = {
        .spics_io_num = SPI_BRIDGE_CS_GPIO,
        .flags = 0,
        .queue_size = SPI_BRIDGE_TRANSACTION_COUNT,
        .mode = 0,
    };

    esp_err_t result = spi_slave_initialize(SPI_BRIDGE_HOST, &bus_config, &slave_config, SPI_DMA_CH_AUTO);
    if (result != ESP_OK) {
        return result;
    }
    result = spi_slave_disable(SPI_BRIDGE_HOST);
    if (result != ESP_OK) {
        return result;
    }

    for (size_t index = 0; index < SPI_BRIDGE_TRANSACTION_COUNT; ++index) {
        void *buffer = spi_bus_dma_memory_alloc(SPI_BRIDGE_HOST, SPI_BRIDGE_BUFFER_SIZE, 0);
        if (buffer == NULL) {
            return ESP_ERR_NO_MEM;
        }
        memset(&s_slots[index].transaction, 0, sizeof(s_slots[index].transaction));
        s_slots[index].transaction.length = SPI_BRIDGE_BUFFER_SIZE * 8;
        s_slots[index].transaction.rx_buffer = buffer;
    }

    if (xTaskCreate(spi_bridge_task, "spi_bridge", 4096, NULL, 6, &s_task) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    s_initialized = true;
    return ESP_OK;
}

esp_err_t spi_bridge_start(void)
{
    if (!s_initialized || s_capturing) {
        return ESP_ERR_INVALID_STATE;
    }

    xSemaphoreTake(s_lock, portMAX_DELAY);
    memset(&s_statistics, 0, sizeof(s_statistics));
    s_ready_head = 0;
    s_ready_count = 0;
    if (s_queued_count == 0) {
        for (size_t index = 0; index < SPI_BRIDGE_TRANSACTION_COUNT; ++index) {
            const esp_err_t result = spi_slave_queue_trans(SPI_BRIDGE_HOST, &s_slots[index].transaction, 0);
            if (result != ESP_OK) {
                s_statistics.spi_dma_errors = saturating_increment(s_statistics.spi_dma_errors);
                s_statistics.event_flags |= SPI_BRIDGE_EVENT_SPI_ERROR;
                xSemaphoreGive(s_lock);
                return result;
            }
            ++s_queued_count;
        }
    }
    s_statistics.available_rx_transactions = s_queued_count;
    s_capturing = true;
    xSemaphoreGive(s_lock);

    const esp_err_t result = spi_slave_enable(SPI_BRIDGE_HOST);
    if (result != ESP_OK) {
        s_capturing = false;
        return result;
    }
    xTaskNotifyGive(s_task);
    return ESP_OK;
}

esp_err_t spi_bridge_stop(void)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_capturing = false;
    xSemaphoreGive(s_lock);
    const esp_err_t result = spi_slave_disable(SPI_BRIDGE_HOST);
    queue_completed_transactions();
    discard_ready_transactions();
    return result;
}

void spi_bridge_on_usb_disconnect(void)
{
    (void)spi_bridge_stop();
    tud_cdc_n_write_clear(0);
}

void spi_bridge_get_statistics(spi_bridge_statistics_t *statistics)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    update_pressure_locked();
    *statistics = s_statistics;
    if (s_starving) {
        statistics->rx_starvation_duration_us += esp_timer_get_time() - s_starvation_started_us;
    }
    xSemaphoreGive(s_lock);
}

uint64_t spi_bridge_finish_stop(uint32_t timeout_ms)
{
    const TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(timeout_ms);
    while (tud_cdc_n_write_available(0) != SPI_BRIDGE_CDC_FIFO_SIZE &&
           xTaskGetTickCount() < deadline && tud_mounted()) {
        tud_cdc_n_write_flush(0);
        vTaskDelay(pdMS_TO_TICKS(1));
    }

    const uint64_t discarded = SPI_BRIDGE_CDC_FIFO_SIZE - tud_cdc_n_write_available(0);
    if (discarded > 0) {
        tud_cdc_n_write_clear(0);
    }
    return discarded;
}
