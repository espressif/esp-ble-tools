# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Provider-centric transport registry.

Each transport backend owns its enumerate/open logic and exposes a PROVIDER..
"""

from __future__ import annotations

from src.backend.models import TransportConfig
from src.backend.support.transport.base import TransportMode
from src.backend.support.transport.base import TransportProvider
from src.backend.support.transport.base import TransportReader
from src.backend.support.transport.spi_usb_bridge_transport import PROVIDER as SPI_USB_BRIDGE_PROVIDER
from src.backend.support.transport.uart_transport import PROVIDER as UART_PROVIDER

_PROVIDERS: tuple[TransportProvider, ...] = (
    UART_PROVIDER,
    SPI_USB_BRIDGE_PROVIDER,
)


def get_transport_provider(mode: TransportMode) -> TransportProvider:
    for provider in _PROVIDERS:
        if provider.mode == mode:
            return provider
    raise ValueError(f'Unsupported transport mode: {mode}')


def list_transport_modes() -> list[tuple[str, TransportMode]]:
    return [(provider.label, provider.mode) for provider in _PROVIDERS]


def list_transport_port_options(mode: TransportMode) -> list[tuple[str, str]]:
    return get_transport_provider(mode).list_options()


def create_transport_reader(config: TransportConfig) -> TransportReader:
    provider = get_transport_provider(config.mode)
    return provider.create_reader(config)
