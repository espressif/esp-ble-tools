#include <inttypes.h>

#include "esp_app_desc.h"
#include "esp_check.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"

#include "bridge_control.h"
#include "spi_bridge.h"
#include "usb_device.h"
#include "usb_ota.h"

#define BRIDGE_FLASH_SIZE (16U * 1024U * 1024U)

static const char *TAG = "ble_log_bridge";

static void confirm_boot_task(void *argument)
{
    (void)argument;
    while (!tud_mounted()) {
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    const esp_err_t result = esp_ota_mark_app_valid_cancel_rollback();
    if (result != ESP_OK && result != ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGE(TAG, "Failed to confirm OTA image: %s", esp_err_to_name(result));
    }
    vTaskDelete(NULL);
}

static esp_err_t verify_flash_contract(void)
{
    uint32_t flash_size;
    ESP_RETURN_ON_ERROR(esp_flash_get_size(NULL, &flash_size), TAG, "Cannot read flash size");
    if (flash_size != BRIDGE_FLASH_SIZE) {
        ESP_LOGE(TAG, "Expected 16 MiB flash, detected %" PRIu32 " bytes", flash_size);
        return ESP_ERR_INVALID_SIZE;
    }
    return ESP_OK;
}

void app_main(void)
{
    ESP_ERROR_CHECK(verify_flash_contract());
    ESP_ERROR_CHECK(spi_bridge_init());
    ESP_ERROR_CHECK(bridge_control_init());
    ESP_ERROR_CHECK(usb_ota_init());
    ESP_ERROR_CHECK(usb_device_init());
    ESP_ERROR_CHECK(xTaskCreate(confirm_boot_task, "confirm_boot", 3072, NULL, 4, NULL) == pdPASS
                        ? ESP_OK
                        : ESP_ERR_NO_MEM);
    ESP_LOGI(TAG, "Bridge ready, firmware %s", esp_app_get_description()->version);
}
