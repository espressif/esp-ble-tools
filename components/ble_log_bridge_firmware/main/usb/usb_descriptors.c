#include "usb_descriptors.h"

#include <stdio.h>

#include "bridge_protocol.h"
#include "esp_mac.h"

#define BRIDGE_USB_VID 0x303A
#define BRIDGE_USB_PID 0x4001
#define BRIDGE_USB_BCD 0x0200
#define BRIDGE_CONFIG_TOTAL_LEN \
    (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_DFU_DESC_LEN(1) + TUD_HID_INOUT_DESC_LEN)

static char s_serial[13];

static const char *s_string_descriptors[] = {
    (const char[]){0x09, 0x04},
    "Espressif",
    "USB-SPI-BRIDGE",
    s_serial,
    "BLE Log Data",
    "Firmware",
    "Bridge Control",
};

static const tusb_desc_device_t s_device_descriptor = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = BRIDGE_USB_BCD,
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = BRIDGE_USB_VID,
    .idProduct = BRIDGE_USB_PID,
    .bcdDevice = 0x0100,
    .iManufacturer = 1,
    .iProduct = 2,
    .iSerialNumber = 3,
    .bNumConfigurations = 1,
};

static const tusb_desc_device_qualifier_t s_device_qualifier = {
    .bLength = sizeof(tusb_desc_device_qualifier_t),
    .bDescriptorType = TUSB_DESC_DEVICE_QUALIFIER,
    .bcdUSB = BRIDGE_USB_BCD,
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .bNumConfigurations = 1,
    .bReserved = 0,
};

static const uint8_t s_hid_report_descriptor[] = {
    0x06, 0x00, 0xFF,       // Usage Page (Vendor 0xFF00)
    0x09, 0x01,             // Usage (1)
    0xA1, 0x01,             // Collection (Application)
    0x85, BRIDGE_REPORT_COMMAND,
    0x09, 0x01,
    0x15, 0x00,
    0x26, 0xFF, 0x00,
    0x75, 0x08,
    0x95, sizeof(bridge_command_report_t),
    0x91, 0x02,
    0x85, BRIDGE_REPORT_RESPONSE,
    0x09, 0x02,
    0x95, sizeof(bridge_response_report_t),
    0x81, 0x02,
    0x85, BRIDGE_REPORT_HEARTBEAT,
    0x09, 0x03,
    0x95, sizeof(bridge_heartbeat_report_t),
    0x81, 0x02,
    0x85, BRIDGE_REPORT_CAPTURE_EVENT,
    0x09, 0x04,
    0x95, sizeof(bridge_capture_event_report_t),
    0x81, 0x02,
    0x85, BRIDGE_REPORT_CAPTURE_STATISTICS,
    0x09, 0x05,
    0x95, sizeof(bridge_capture_statistics_report_t),
    0x81, 0x02,
    0xC0,
};

#define BRIDGE_DFU_ATTRIBUTES DFU_ATTR_CAN_DOWNLOAD
#define BRIDGE_CONFIGURATION_DESCRIPTOR(_bulk_size) \
    TUD_CONFIG_DESCRIPTOR(1, 4, 0, BRIDGE_CONFIG_TOTAL_LEN, TUSB_DESC_CONFIG_ATT_REMOTE_WAKEUP, 100), \
    TUD_CDC_DESCRIPTOR(0, 4, 0x81, 8, 0x02, 0x82, _bulk_size), \
    TUD_DFU_DESCRIPTOR(2, 1, 5, BRIDGE_DFU_ATTRIBUTES, 1000, 4096), \
    TUD_HID_INOUT_DESCRIPTOR(3, 6, HID_ITF_PROTOCOL_NONE, sizeof(s_hid_report_descriptor), 0x03, 0x83, 64, 4)

static const uint8_t s_fs_configuration_descriptor[] = {
    BRIDGE_CONFIGURATION_DESCRIPTOR(64),
};

static const uint8_t s_hs_configuration_descriptor[] = {
    BRIDGE_CONFIGURATION_DESCRIPTOR(512),
};

_Static_assert(sizeof(s_fs_configuration_descriptor) == BRIDGE_CONFIG_TOTAL_LEN,
               "full-speed descriptor length mismatch");
_Static_assert(sizeof(s_hs_configuration_descriptor) == BRIDGE_CONFIG_TOTAL_LEN,
               "high-speed descriptor length mismatch");

static void set_serial(void)
{
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_BASE));
    snprintf(s_serial, sizeof(s_serial), "%02X%02X%02X%02X%02X%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

void usb_descriptors_apply(tinyusb_config_t *config)
{
    set_serial();
    config->descriptor.device = &s_device_descriptor;
    config->descriptor.qualifier = &s_device_qualifier;
    config->descriptor.string = s_string_descriptors;
    config->descriptor.string_count = sizeof(s_string_descriptors) / sizeof(s_string_descriptors[0]);
    config->descriptor.full_speed_config = s_fs_configuration_descriptor;
    config->descriptor.high_speed_config = s_hs_configuration_descriptor;
}

uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance)
{
    (void)instance;
    return s_hid_report_descriptor;
}
