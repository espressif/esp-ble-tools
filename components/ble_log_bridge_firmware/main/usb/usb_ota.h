#pragma once

#include "esp_err.h"

esp_err_t usb_ota_init(void);
void usb_ota_abort(void);
