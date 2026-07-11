#include "usb_ota.h"

#include <stdbool.h>

#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "tusb.h"

#include "bridge_control.h"

typedef enum {
    OTA_IDLE,
    OTA_RECEIVING,
    OTA_REBOOT_PENDING,
} ota_state_t;

static ota_state_t s_state;
static const esp_partition_t *s_target;
static esp_ota_handle_t s_handle;
static uint16_t s_next_block;
static size_t s_received_bytes;
static esp_timer_handle_t s_reboot_timer;

static void reboot_timer_callback(void *argument)
{
    (void)argument;
    esp_restart();
}

static void reset_session(bool abort_handle)
{
    if (abort_handle && s_state == OTA_RECEIVING) {
        (void)esp_ota_abort(s_handle);
    }
    s_state = OTA_IDLE;
    s_target = NULL;
    s_handle = 0;
    s_next_block = 0;
    s_received_bytes = 0;
    bridge_control_end_update();
}

static dfu_status_t begin_session(uint8_t alt)
{
    if (alt != 0 || !bridge_control_begin_update()) {
        return DFU_STATUS_ERR_NOTDONE;
    }

    s_target = esp_ota_get_next_update_partition(NULL);
    const esp_partition_t *running = esp_ota_get_running_partition();
    if (s_target == NULL || s_target == running || s_target->type != ESP_PARTITION_TYPE_APP) {
        reset_session(false);
        return DFU_STATUS_ERR_TARGET;
    }

    if (esp_ota_begin(s_target, OTA_WITH_SEQUENTIAL_WRITES, &s_handle) != ESP_OK) {
        reset_session(false);
        return DFU_STATUS_ERR_WRITE;
    }
    s_state = OTA_RECEIVING;
    return DFU_STATUS_OK;
}

esp_err_t usb_ota_init(void)
{
    const esp_timer_create_args_t timer_args = {
        .callback = reboot_timer_callback,
        .name = "ota_reboot",
    };
    return esp_timer_create(&timer_args, &s_reboot_timer);
}

void usb_ota_abort(void)
{
    if (s_state == OTA_RECEIVING) {
        reset_session(true);
    }
}

uint32_t tud_dfu_get_timeout_cb(uint8_t alt, uint8_t state)
{
    (void)alt;
    return state == DFU_DNBUSY ? 100 : 1000;
}

void tud_dfu_download_cb(uint8_t alt, uint16_t block_num, const uint8_t *data, uint16_t length)
{
    dfu_status_t status = DFU_STATUS_OK;
    if (s_state == OTA_IDLE) {
        if (block_num != 0) {
            status = DFU_STATUS_ERR_ADDRESS;
        } else {
            status = begin_session(alt);
        }
    }

    if (status == DFU_STATUS_OK && s_state != OTA_RECEIVING) {
        status = DFU_STATUS_ERR_NOTDONE;
    }
    if (status == DFU_STATUS_OK && block_num != s_next_block) {
        status = DFU_STATUS_ERR_ADDRESS;
    }
    if (status == DFU_STATUS_OK && s_received_bytes + length > s_target->size) {
        status = DFU_STATUS_ERR_ADDRESS;
    }
    if (status == DFU_STATUS_OK && esp_ota_write(s_handle, data, length) != ESP_OK) {
        status = DFU_STATUS_ERR_WRITE;
    }

    if (status == DFU_STATUS_OK) {
        ++s_next_block;
        s_received_bytes += length;
    } else if (s_state == OTA_RECEIVING) {
        reset_session(true);
    }
    tud_dfu_finish_flashing(status);
}

void tud_dfu_manifest_cb(uint8_t alt)
{
    (void)alt;
    dfu_status_t status = DFU_STATUS_OK;
    if (s_state != OTA_RECEIVING || s_received_bytes == 0) {
        status = DFU_STATUS_ERR_NOTDONE;
    } else if (esp_ota_end(s_handle) != ESP_OK) {
        s_handle = 0;
        s_state = OTA_IDLE;
        bridge_control_end_update();
        status = DFU_STATUS_ERR_VERIFY;
    } else if (esp_ota_set_boot_partition(s_target) != ESP_OK) {
        s_handle = 0;
        s_state = OTA_IDLE;
        bridge_control_end_update();
        status = DFU_STATUS_ERR_FIRMWARE;
    } else {
        s_handle = 0;
        s_state = OTA_REBOOT_PENDING;
    }

    tud_dfu_finish_flashing(status);
    if (status == DFU_STATUS_OK) {
        (void)esp_timer_start_once(s_reboot_timer, 250000);
    }
}

uint16_t tud_dfu_upload_cb(uint8_t alt, uint16_t block_num, uint8_t *data, uint16_t length)
{
    (void)alt;
    (void)block_num;
    (void)data;
    (void)length;
    return 0;
}

void tud_dfu_abort_cb(uint8_t alt)
{
    (void)alt;
    usb_ota_abort();
}

void tud_dfu_detach_cb(void)
{
}
