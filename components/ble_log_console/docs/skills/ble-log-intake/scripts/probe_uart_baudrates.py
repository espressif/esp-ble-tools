# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

"""Probe driver acceptance of UART baud rates; does not measure link quality."""

import argparse
import platform

BAUDRATES = (
    115200,
    230400,
    460800,
    500000,
    576000,
    921600,
    1000000,
    1152000,
    1500000,
    2000000,
    2500000,
    3000000,
    3500000,
    4000000,
)


def probe(port: str) -> int:
    import serial

    print(f'Port: {port}')
    print(f'OS: {platform.system()} {platform.release()}')
    print(f'pySerial: {serial.VERSION}')
    print('ACCEPTED = driver accepted the request, NOT a transmission test.')
    print('Property = pySerial baudrate setting, NOT measured wire speed.')
    print('No data is sent/read. Opening the port may reset some boards via DTR/RTS.')
    print('Close other serial programs before probing. FAIL may also mean access/device errors.')
    print(f'\n{"Requested":<12} {"Result":<10} {"Property":<12}')

    accepted = 0
    for baud in BAUDRATES:
        try:
            # Open only after setting control lines; drivers may still glitch them.
            with serial.Serial(port=None, baudrate=baud, timeout=0.1) as connection:
                connection.port = port
                connection.dtr = False
                connection.rts = False
                connection.open()
                configured = connection.baudrate
        except (OSError, ValueError) as error:
            print(f'{baud:<12} {"FAIL":<10} {"-":<12} ({type(error).__name__}: {error})')
        else:
            accepted += 1
            print(f'{baud:<12} {"ACCEPTED":<10} {configured:<12}')

    print(f'\nAccepted requests: {accepted}/{len(BAUDRATES)}. Link quality remains unverified.')
    return 0 if accepted else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port', help='Actual serial port, e.g. COM3 or /dev/ttyUSB0')
    args = parser.parse_args()
    try:
        return probe(args.port)
    except ImportError:
        parser.exit(2, 'Missing pyserial. Install with this Python: python -m pip install pyserial\n')


if __name__ == '__main__':
    raise SystemExit(main())
