idf_component_register(
    SRCS
        "app_main.c"
        "bridge/bridge_control.c"
        "spi/spi_bridge.c"
        "usb/usb_descriptors.c"
        "usb/usb_device.c"
        "usb/usb_ota.c"
    PRIV_INCLUDE_DIRS
        "."
        "bridge"
        "spi"
        "usb"
    PRIV_REQUIRES app_update esp_driver_spi esp_system esp_timer espressif__esp_tinyusb spi_flash
)
