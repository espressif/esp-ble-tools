#pragma once

#include <stdbool.h>

#include "esp_err.h"

#include "bridge_protocol.h"

esp_err_t bridge_control_init(void);
bool bridge_control_begin_update(void);
void bridge_control_end_update(void);
void bridge_control_usb_disconnected(void);
