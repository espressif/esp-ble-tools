# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""USB-SPI bridge transport for BLE log byte streams."""

from __future__ import annotations

import errno
import sys
from dataclasses import dataclass

import serial
import serial.tools.list_ports
import usb.core
import usb.util

from src.backend.models import TransportConfig
from src.backend.models import TransportBitrate
from src.backend.support.transport.base import TransportMode
from src.backend.support.transport.base import TransportProvider
from src.backend.support.transport.base import TransportStatus

VENDOR_ID = 0x303A
PRODUCT_ID = 0x4001
DEVICE_DESCRIPTION = 'USB-SPI-BRIDGE'

SPI_BITS_PER_BYTE = 8
SPI_USB_RX_BUFFER_SIZE = 20 * 1024
SPI_WIRE_BPS = 20_000_000
USB_TIMEOUT_MS = 100
USB_TIMEOUT_ERRNO = 110
USB_DISCONNECT_ERRNOS = {
    errno.ENODEV,
    errno.EIO,
    getattr(errno, 'ESHUTDOWN', 108),
    getattr(errno, 'ECONNRESET', 104),
}
CDC_ENDPOINT_PREFIX = 'cdc:'


@dataclass(frozen=True)
class SpiUsbBridgeEndpoint:
    """Stable USB bulk endpoint identity passed through the frontend Select value."""

    bus: int
    address: int
    interface: int
    endpoint: int

    @property
    def key(self) -> str:
        return f'{self.bus}:{self.address}:{self.interface}:{self.endpoint}'

    @property
    def label(self) -> str:
        return (
            f'{DEVICE_DESCRIPTION} '
            f'bus={self.bus} addr={self.address} intf={self.interface} ep=0x{self.endpoint:02x}'
        )


@dataclass
class EndpointAccess:
    """Opened USB objects needed to read from the bridge bulk IN endpoint."""

    device: usb.core.Device
    interface: usb.core.Interface
    ep: usb.core.Endpoint


def _endpoint_from_key(key: str) -> SpiUsbBridgeEndpoint:
    try:
        bus, address, interface, endpoint = (int(part) for part in key.split(':'))
    except ValueError as e:
        raise ValueError(f'Invalid USB-SPI bridge endpoint key: {key}') from e
    return SpiUsbBridgeEndpoint(bus=bus, address=address, interface=interface, endpoint=endpoint)


def _is_usb_timeout(error: usb.core.USBError) -> bool:
    return error.errno == USB_TIMEOUT_ERRNO or 'time out' in str(error).lower()


def _is_usb_disconnect(error: usb.core.USBError) -> bool:
    message = str(error).lower()
    return (
        error.errno in USB_DISCONNECT_ERRNOS
        or 'no such device' in message
        or 'disconnected' in message
        or 'device has been disconnected' in message
    )


def _detach_kernel_driver(target_device: usb.core.Device, target_interface: usb.core.Interface) -> None:
    interface_num = getattr(target_interface, 'bInterfaceNumber', None)
    if not isinstance(interface_num, int):
        return
    try:
        if target_device.is_kernel_driver_active(interface_num):
            target_device.detach_kernel_driver(interface_num)
    except (NotImplementedError, usb.core.USBError):
        pass


def _find_endpoint_access(endpoint: SpiUsbBridgeEndpoint) -> EndpointAccess:
    target_device = usb.core.find(bus=endpoint.bus, address=endpoint.address)
    if not isinstance(target_device, usb.core.Device):
        raise RuntimeError(f'Device on bus {endpoint.bus} with addr {endpoint.address} not found')

    target_config = target_device.get_active_configuration()
    if not isinstance(target_config, usb.core.Configuration):
        raise RuntimeError('USB configuration was not found')

    target_interface = None
    for curr_interface in target_config:
        if not isinstance(curr_interface, usb.core.Interface):
            continue
        interface_num = getattr(curr_interface, 'bInterfaceNumber', None)
        if isinstance(interface_num, int) and interface_num == endpoint.interface:
            target_interface = curr_interface
            break

    if target_interface is None:
        raise RuntimeError(f'USB interface {endpoint.interface} was not found')

    target_ep = None
    for curr_ep in target_interface:
        if not isinstance(curr_ep, usb.core.Endpoint):
            continue
        ep_addr = getattr(curr_ep, 'bEndpointAddress', None)
        if isinstance(ep_addr, int) and ep_addr == endpoint.endpoint:
            target_ep = curr_ep
            break

    if target_ep is None:
        raise RuntimeError(f'USB endpoint 0x{endpoint.endpoint:02x} was not found')

    _detach_kernel_driver(target_device, target_interface)
    return EndpointAccess(device=target_device, interface=target_interface, ep=target_ep)


def list_spi_usb_bridge_bulk_endpoints() -> list[SpiUsbBridgeEndpoint]:
    target_devices = usb.core.find(find_all=True, idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if target_devices is None:
        return []
    if isinstance(target_devices, usb.core.Device):
        target_devices = [target_devices]

    endpoints: list[SpiUsbBridgeEndpoint] = []
    for target_device in target_devices:
        if not isinstance(target_device, usb.core.Device):
            continue
        try:
            target_config = target_device.get_active_configuration()
        except Exception:
            continue

        for target_interface in target_config:
            if not isinstance(target_interface, usb.core.Interface):
                continue
            interface_num = getattr(target_interface, 'bInterfaceNumber', None)
            if not isinstance(interface_num, int):
                continue

            for target_ep in target_interface:
                if not isinstance(target_ep, usb.core.Endpoint):
                    continue
                ep_addr = getattr(target_ep, 'bEndpointAddress', None)
                ep_attributes = getattr(target_ep, 'bmAttributes', None)
                if not isinstance(ep_addr, int) or not isinstance(ep_attributes, int):
                    continue
                if usb.util.endpoint_direction(ep_addr) != usb.util.ENDPOINT_IN:
                    continue
                if usb.util.endpoint_type(ep_attributes) != usb.util.ENDPOINT_TYPE_BULK:
                    continue
                endpoints.append(
                    SpiUsbBridgeEndpoint(
                        bus=int(target_device.bus),
                        address=int(target_device.address),
                        interface=interface_num,
                        endpoint=ep_addr,
                    )
                )

        usb.util.dispose_resources(target_device)

    return endpoints


def _is_windows() -> bool:
    return sys.platform == 'win32'


def _is_spi_usb_bridge_port(port: object) -> bool:
    vid = getattr(port, 'vid', None)
    pid = getattr(port, 'pid', None)
    if vid == VENDOR_ID and pid == PRODUCT_ID:
        return True

    text_parts = (
        getattr(port, 'description', ''),
        getattr(port, 'hwid', ''),
        getattr(port, 'manufacturer', ''),
        getattr(port, 'product', ''),
        getattr(port, 'interface', ''),
    )
    text = ' '.join(str(part) for part in text_parts if part).lower()
    return '303a' in text and '4001' in text


def list_spi_usb_bridge_cdc_options() -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    for port in serial.tools.list_ports.comports():
        if not _is_spi_usb_bridge_port(port):
            continue
        device = str(port.device)
        label = f'{DEVICE_DESCRIPTION} CDC {device}'
        options.append((label, f'{CDC_ENDPOINT_PREFIX}{device}'))
    return options


def list_spi_usb_bridge_port_options() -> list[tuple[str, str]]:
    if _is_windows():
        cdc_options = list_spi_usb_bridge_cdc_options()
        if cdc_options:
            return cdc_options

    return [(endpoint.label, endpoint.key) for endpoint in list_spi_usb_bridge_bulk_endpoints()]


class SpiUsbBridgeCdcTransport:
    def __init__(self, port: str, baudrate: int) -> None:
        self._port = port
        self._baudrate = baudrate
        self._serial: serial.Serial | None = None
        self._rx_bytes = 0
        self._rx_chunks = 0
        self._last_error: str | None = None

    @property
    def display_name(self) -> str:
        return f'{DEVICE_DESCRIPTION} CDC {self._port}'

    @property
    def block_size(self) -> int:
        return SPI_USB_RX_BUFFER_SIZE

    @property
    def bitrate_config(self) -> TransportBitrate:
        return TransportBitrate(
            bits_per_payload_byte=SPI_BITS_PER_BYTE,
            wire_bits_per_sec=float(SPI_WIRE_BPS),
        )

    def open(self) -> None:
        if self._serial is not None and self._serial.is_open:
            return
        try:
            self._serial = serial.Serial(self._port, baudrate=self._baudrate, timeout=USB_TIMEOUT_MS / 1000)
            self._last_error = None
        except serial.SerialException as e:
            self._last_error = str(e)
            raise RuntimeError(f'Failed to connect to the USB-SPI bridge CDC port {self._port}: {e}') from e

    def read(self, size: int | None = None) -> bytes:
        if self._serial is None or not self._serial.is_open:
            raise RuntimeError('USB-SPI bridge CDC transport is not open')
        block = self._serial.read(size or self.block_size)  # type: ignore[no-any-return]
        if block:
            self._rx_bytes += len(block)
            self._rx_chunks += 1
        return block

    def drain(self, max_rounds: int = 10) -> list[bytes]:
        blocks: list[bytes] = []
        for _ in range(max_rounds):
            block = self.read()
            if not block:
                break
            blocks.append(block)
        return blocks

    def close(self) -> None:
        if self._serial is None:
            return
        self._serial.close()

    def reset_target(self) -> bool:
        return False

    def status(self) -> TransportStatus:
        opened = self._serial is not None and self._serial.is_open
        return TransportStatus(
            mode=TransportMode.SPI_USB_BRIDGE,
            display_name=self.display_name,
            opened=opened,
            healthy=opened and self._last_error is None,
            rx_bytes=self._rx_bytes,
            rx_chunks=self._rx_chunks,
            last_error=self._last_error,
        )


class SpiUsbBridgeBulkTransport:
    def __init__(self, endpoint: SpiUsbBridgeEndpoint) -> None:
        self._endpoint = endpoint
        self._epa: EndpointAccess | None = None
        self._claimed = False
        self._rx_bytes = 0
        self._rx_chunks = 0
        self._last_error: str | None = None

    def open(self) -> None:
        if self._claimed:
            return
        self._epa = _find_endpoint_access(self._endpoint)
        try:
            usb.util.claim_interface(self._epa.device, self._epa.interface)
        except Exception as e:
            usb.util.dispose_resources(self._epa.device)
            self._epa = None
            self._last_error = str(e)
            raise RuntimeError(
                f'Failed to connect to the USB-SPI bridge: {e}\n'
                'Please check the cable connection and make sure the device is not already open '
                'in another terminal or process.'
            ) from e
        self._claimed = True
        self._last_error = None

    @property
    def display_name(self) -> str:
        return self._endpoint.label

    @property
    def block_size(self) -> int:
        return SPI_USB_RX_BUFFER_SIZE

    @property
    def bitrate_config(self) -> TransportBitrate:
        return TransportBitrate(
            bits_per_payload_byte=SPI_BITS_PER_BYTE,
            wire_bits_per_sec=float(SPI_WIRE_BPS),
        )

    def read(self, size: int | None = None) -> bytes:
        if self._epa is None or not self._claimed:
            raise RuntimeError('USB-SPI bridge bulk transport is not open')
        try:
            rx_data = self._epa.device.read(self._epa.ep, size or self.block_size, USB_TIMEOUT_MS)
        except usb.core.USBError as e:
            if _is_usb_timeout(e):
                return b''
            if _is_usb_disconnect(e):
                self._last_error = 'USB-SPI bridge disconnected or reset'
                raise RuntimeError('USB-SPI bridge disconnected or reset') from e
            self._last_error = str(e)
            raise RuntimeError(f'USB-SPI bridge read failed: {e}') from e
        block = rx_data.tobytes() if rx_data else b''
        if block:
            self._rx_bytes += len(block)
            self._rx_chunks += 1
        return block

    def drain(self, max_rounds: int = 10) -> list[bytes]:
        blocks: list[bytes] = []
        for _ in range(max_rounds):
            block = self.read()
            if not block:
                break
            blocks.append(block)
        return blocks

    def close(self) -> None:
        if self._epa is None:
            return
        try:
            if self._claimed:
                usb.util.release_interface(self._epa.device, self._epa.interface)
        except usb.core.USBError:
            pass
        finally:
            self._claimed = False

        try:
            usb.util.dispose_resources(self._epa.device)
        except usb.core.USBError:
            pass
        finally:
            self._epa = None

    def reset_target(self) -> bool:
        return False

    def status(self) -> TransportStatus:
        return TransportStatus(
            mode=TransportMode.SPI_USB_BRIDGE,
            display_name=self.display_name,
            opened=self._claimed,
            healthy=self._claimed and self._last_error is None,
            rx_bytes=self._rx_bytes,
            rx_chunks=self._rx_chunks,
            last_error=self._last_error,
        )


def _cdc_port_from_key(port_key: str) -> str:
    if port_key.startswith(CDC_ENDPOINT_PREFIX):
        return port_key[len(CDC_ENDPOINT_PREFIX):]
    return port_key


class SpiUsbBridgeTransportProvider:
    @property
    def label(self) -> str:
        return 'SPI USB Bridge'

    @property
    def mode(self) -> TransportMode:
        return TransportMode.SPI_USB_BRIDGE

    def list_options(self) -> list[tuple[str, str]]:
        return list_spi_usb_bridge_port_options()

    def create_reader(self, config: TransportConfig) -> SpiUsbBridgeCdcTransport | SpiUsbBridgeBulkTransport:
        if config.port.startswith(CDC_ENDPOINT_PREFIX):
            return SpiUsbBridgeCdcTransport(_cdc_port_from_key(config.port), config.baudrate)
        return SpiUsbBridgeBulkTransport(_endpoint_from_key(config.port))


PROVIDER: TransportProvider = SpiUsbBridgeTransportProvider()
