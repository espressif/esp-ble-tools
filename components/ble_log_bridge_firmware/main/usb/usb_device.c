#include "usb_device.h"

#include "tinyusb_default_config.h"

#include "bridge_control.h"
#include "usb_descriptors.h"
#include "usb_ota.h"

static void usb_event_callback(tinyusb_event_t *event, void *argument)
{
    (void)argument;
    if (event->id == TINYUSB_EVENT_DETACHED) {
        usb_ota_abort();
        bridge_control_usb_disconnected();
    }
}

esp_err_t usb_device_init(void)
{
    tinyusb_config_t config = TINYUSB_DEFAULT_CONFIG(usb_event_callback);
    config.port = TINYUSB_PORT_HIGH_SPEED_0;
    usb_descriptors_apply(&config);
    return tinyusb_driver_install(&config);
}
