# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: cdivision=True

"""Cython checksum hot-path implementations."""

from libc.stdint cimport uint32_t


cpdef unsigned int sum_checksum_range(const unsigned char[:] data, Py_ssize_t offset, Py_ssize_t length):
    cdef Py_ssize_t data_len = data.shape[0]
    cdef Py_ssize_t i
    cdef Py_ssize_t end
    cdef uint32_t checksum = 0

    if offset < 0 or length < 0 or offset + length > data_len:
        raise ValueError('checksum range out of bounds')

    end = offset + length
    for i in range(offset, end):
        checksum += data[i]

    return checksum


cpdef unsigned int xor_checksum_range(const unsigned char[:] data, Py_ssize_t offset, Py_ssize_t length):
    cdef Py_ssize_t data_len = data.shape[0]
    cdef Py_ssize_t i
    cdef Py_ssize_t full_end
    cdef Py_ssize_t end
    cdef uint32_t checksum = 0
    cdef uint32_t word
    cdef int shift

    if offset < 0 or length < 0 or offset + length > data_len:
        raise ValueError('checksum range out of bounds')

    full_end = offset + (length & ~3)
    end = offset + length
    i = offset
    while i < full_end:
        word = (
            (<uint32_t>data[i])
            | ((<uint32_t>data[i + 1]) << 8)
            | ((<uint32_t>data[i + 2]) << 16)
            | ((<uint32_t>data[i + 3]) << 24)
        )
        checksum ^= word
        i += 4

    if i < end:
        word = 0
        shift = 0
        while i < end:
            word |= (<uint32_t>data[i]) << shift
            shift += 8
            i += 1
        checksum ^= word

    return checksum
