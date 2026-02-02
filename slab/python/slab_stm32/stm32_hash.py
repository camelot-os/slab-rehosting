"""
STM32F4 HASH Peripheral (Hash Processor)

Supports:
- MD5 (128-bit digest)
- SHA-1 (160-bit digest)
- SHA-224 (224-bit digest)
- SHA-256 (256-bit digest)
- HMAC mode

Register layout follows STM32F4 reference manual (RM0090).

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
import hashlib
import hmac
from typing import Optional, Callable
from .stm32_base import STM32Peripheral


class STM32F4HASH(STM32Peripheral):
    """
    STM32F4 HASH (Hash Processor).

    Register Map (offset from base 0x50060400):
        0x00: CR        - Control register
        0x04: DIN       - Data input register
        0x08: STR       - Start register
        0x0C-0x1C: HR[0-4] - Hash digest registers (for MD5/SHA-1)
        0x20: IMR       - Interrupt mask register
        0x24: SR        - Status register
        0x28: Reserved
        0x2C-0x3C: CSR[0-53] - Context swap registers
        0xF8: Reserved
        0x310-0x32C: HR[5-7] - Extended hash digest (for SHA-224/256)

    CR Register Bits:
        [1:0]   Reserved
        [2]     INIT        Initialize hash processor
        [3]     DMAE        DMA enable
        [5:4]   DATATYPE    00=32-bit, 01=16-bit, 10=8-bit, 11=1-bit swap
        [6]     MODE        0=hash, 1=HMAC
        [7]     ALGO0       Algorithm bit 0
        [11:8]  NBW         Number of words already pushed
        [12]    DINNE       Data input not empty
        [13]    MDMAT       Multiple DMA transfers
        [15:14] Reserved
        [16]    LKEY        Long key (>64 bytes for HMAC)
        [17]    Reserved
        [18]    ALGO1       Algorithm bit 1

    Algorithm Selection:
        ALGO1:ALGO0
        0:0 = SHA-1
        0:1 = MD5
        1:0 = SHA-224
        1:1 = SHA-256

    STR Register:
        [4:0]   NBLW    Number of valid bits in last word (0-31)
        [7:5]   Reserved
        [8]     DCAL    Digest calculation (write 1 to compute)

    SR Register:
        [0]     DINIS   Data input interrupt status
        [1]     DCIS    Digest calculation complete interrupt status
        [2]     DMAS    DMA status
        [3]     BUSY    Busy
    """

    # Register offsets
    CR = 0x00
    DIN = 0x04
    STR = 0x08
    HR0 = 0x0C
    HR1 = 0x10
    HR2 = 0x14
    HR3 = 0x18
    HR4 = 0x1C
    IMR = 0x20
    SR = 0x24

    # Extended hash registers (for SHA-224/256)
    HR5 = 0x310
    HR6 = 0x314
    HR7 = 0x318
    HR8 = 0x31C  # Not used but reserved

    # Context swap registers
    CSR_BASE = 0x2C

    # CR bits
    CR_INIT = 1 << 2
    CR_DMAE = 1 << 3
    CR_DATATYPE_MASK = 0x3 << 4
    CR_MODE = 1 << 6       # 0=hash, 1=HMAC
    CR_ALGO0 = 1 << 7
    CR_NBW_MASK = 0xF << 8
    CR_DINNE = 1 << 12
    CR_MDMAT = 1 << 13
    CR_LKEY = 1 << 16
    CR_ALGO1 = 1 << 18

    # STR bits
    STR_NBLW_MASK = 0x1F
    STR_DCAL = 1 << 8

    # SR bits
    SR_DINIS = 1 << 0   # Data input interrupt status
    SR_DCIS = 1 << 1    # Digest calculation complete
    SR_DMAS = 1 << 2    # DMA status
    SR_BUSY = 1 << 3    # Busy

    # IMR bits
    IMR_DINIE = 1 << 0   # Data input interrupt enable
    IMR_DCIE = 1 << 1    # Digest calculation interrupt enable

    def __init__(self, base: int = 0x50060400):
        super().__init__("HASH", base, 0x400, irq=80)

        # Registers
        self.cr = 0
        self.str = 0
        self.sr = self.SR_DINIS  # Ready for input
        self.imr = 0

        # Hash result (up to 256 bits = 8 words)
        self.hr = [0] * 8

        # Context swap registers
        self.csr = [0] * 54

        # Input buffer
        self.din_buf = bytearray()

        # HMAC key storage
        self.hmac_key = b''

        self.log = logging.getLogger("STM32.HASH")

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self._get_cr()
        elif offset == self.STR:
            return self.str
        elif offset == self.SR:
            return self.sr
        elif offset == self.IMR:
            return self.imr
        elif offset == self.HR0:
            return self.hr[0]
        elif offset == self.HR1:
            return self.hr[1]
        elif offset == self.HR2:
            return self.hr[2]
        elif offset == self.HR3:
            return self.hr[3]
        elif offset == self.HR4:
            return self.hr[4]
        elif offset == self.HR5:
            return self.hr[5]
        elif offset == self.HR6:
            return self.hr[6]
        elif offset == self.HR7:
            return self.hr[7]
        elif self.CSR_BASE <= offset < self.CSR_BASE + 54 * 4:
            idx = (offset - self.CSR_BASE) // 4
            return self.csr[idx] if idx < 54 else 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self._write_cr(value)
        elif offset == self.DIN:
            self._write_din(value)
        elif offset == self.STR:
            self._write_str(value)
        elif offset == self.IMR:
            self.imr = value
        elif self.CSR_BASE <= offset < self.CSR_BASE + 54 * 4:
            idx = (offset - self.CSR_BASE) // 4
            if idx < 54:
                self.csr[idx] = value

    def _get_cr(self) -> int:
        """Get CR with dynamic NBW and DINNE fields."""
        cr = self.cr
        # NBW: number of words pushed
        nbw = len(self.din_buf) // 4
        cr = (cr & ~self.CR_NBW_MASK) | ((nbw & 0xF) << 8)
        # DINNE: data input not empty
        if len(self.din_buf) > 0:
            cr |= self.CR_DINNE
        else:
            cr &= ~self.CR_DINNE
        return cr

    def _write_cr(self, value: int):
        """Write to control register."""
        if value & self.CR_INIT:
            # Initialize hash processor
            self.din_buf = bytearray()
            self.hr = [0] * 8
            self.sr |= self.SR_DINIS
            self.sr &= ~(self.SR_DCIS | self.SR_BUSY)

        self.cr = value & ~self.CR_INIT  # INIT is write-only, auto-clear

    def _write_din(self, value: int):
        """Write to data input register.

        The DATATYPE field controls byte reordering of the incoming word:
          - 00 (32-bit): No reordering. On LE bus, bytes stay in bus order (LE).
          - 01 (16-bit): Half-word swap within each word.
          - 10 (8-bit):  Full byte swap (LE → BE). Most common for hash input.
          - 11 (1-bit):  Bit reversal (rarely used).

        The hash algorithm processes data as a big-endian byte stream.
        DATATYPE=2 (byte swap) converts LE bus data to BE for the hash engine.
        """
        datatype = (self.cr >> 4) & 0x3

        if datatype == 0:  # 32-bit: no reordering, LE bus order
            data = value.to_bytes(4, 'little')
        elif datatype == 1:  # 16-bit: half-word swap
            b = value.to_bytes(4, 'little')
            data = bytes([b[1], b[0], b[3], b[2]])
        elif datatype == 2:  # 8-bit: byte swap (LE → BE, most common)
            data = value.to_bytes(4, 'big')
        else:  # 1-bit: bit reverse (rarely used)
            data = value.to_bytes(4, 'little')

        self.din_buf.extend(data)
        self.sr &= ~self.SR_DINIS  # No longer ready for input (processing)

    def _write_str(self, value: int):
        """Write to start register."""
        self.str = value & self.STR_NBLW_MASK

        if value & self.STR_DCAL:
            # Trigger digest calculation
            self._compute_hash()

    def _swap_bytes(self, data: bytes, datatype: int) -> bytes:
        """Apply data type byte swapping."""
        if datatype == 0:  # 32-bit (no swap within word, but we receive in LE)
            return bytes(reversed(data))
        elif datatype == 1:  # 16-bit half-word swap
            return bytes([data[1], data[0], data[3], data[2]])
        elif datatype == 2:  # 8-bit byte swap (data as-is)
            return data
        else:  # 1-bit swap (bit reverse, rarely used)
            return data

    def _get_algorithm(self):
        """Get hash algorithm from CR."""
        algo0 = 1 if (self.cr & self.CR_ALGO0) else 0
        algo1 = 1 if (self.cr & self.CR_ALGO1) else 0
        algo = (algo1 << 1) | algo0

        if algo == 0:
            return 'sha1'
        elif algo == 1:
            return 'md5'
        elif algo == 2:
            return 'sha224'
        else:
            return 'sha256'

    def _compute_hash(self):
        """Compute the hash digest."""
        self.sr |= self.SR_BUSY

        algo = self._get_algorithm()
        is_hmac = bool(self.cr & self.CR_MODE)

        # Handle last word bit count - NBLW indicates valid bits in final partial word
        data = bytes(self.din_buf)
        nblw = self.str & self.STR_NBLW_MASK
        if nblw > 0 and len(data) >= 4:
            # NBLW: number of valid bits in the last word written
            valid_bytes_last = nblw // 8
            trim = 4 - valid_bytes_last
            if trim > 0:
                data = data[:-trim]

        try:
            if is_hmac:
                # HMAC mode
                h = hmac.new(self.hmac_key, data, algo)
                digest = h.digest()
            else:
                # Regular hash
                h = hashlib.new(algo, data)
                digest = h.digest()

            # Store result in HR registers (big-endian words)
            digest_len = len(digest)
            for i in range(min(digest_len // 4, 8)):
                self.hr[i] = int.from_bytes(digest[i*4:(i+1)*4], 'big')

            # Clear unused registers
            for i in range(digest_len // 4, 8):
                self.hr[i] = 0

        except Exception as e:
            self.log.error(f"Hash computation error: {e}")

        self.sr &= ~self.SR_BUSY
        self.sr |= self.SR_DCIS | self.SR_DINIS

        # Trigger interrupt if enabled
        if self.imr & self.IMR_DCIE:
            self.trigger_irq()

    # Convenience methods for testing

    def set_algorithm(self, algo: str):
        """Set hash algorithm (convenience method)."""
        self.cr &= ~(self.CR_ALGO0 | self.CR_ALGO1)
        if algo == 'sha1':
            pass  # 00
        elif algo == 'md5':
            self.cr |= self.CR_ALGO0  # 01
        elif algo == 'sha224':
            self.cr |= self.CR_ALGO1  # 10
        elif algo == 'sha256':
            self.cr |= self.CR_ALGO0 | self.CR_ALGO1  # 11

    def set_hmac_key(self, key: bytes):
        """Set HMAC key (convenience method)."""
        self.hmac_key = key
        self.cr |= self.CR_MODE

    def hash_data(self, data: bytes) -> bytes:
        """Hash data and return digest (convenience method)."""
        # Initialize - use 8-bit data type (native byte order)
        self.cr = (self.cr & ~self.CR_DATATYPE_MASK) | (2 << 4)  # DATATYPE = 8-bit
        self._write_cr(self.cr | self.CR_INIT)

        # For convenience method, directly set the data buffer
        # This bypasses the register interface complexity
        self.din_buf = bytearray(data)

        # Calculate remaining bits in last word
        remainder = len(data) % 4
        if remainder:
            nblw = remainder * 8
        else:
            nblw = 0

        # Trigger calculation
        self._write_str(self.STR_DCAL | nblw)

        # Read result
        algo = self._get_algorithm()
        if algo == 'md5':
            digest_len = 16
        elif algo == 'sha1':
            digest_len = 20
        elif algo == 'sha224':
            digest_len = 28
        else:  # sha256
            digest_len = 32

        result = b''
        for i in range(digest_len // 4):
            result += self.hr[i].to_bytes(4, 'big')

        return result

    def hmac_data(self, key: bytes, data: bytes) -> bytes:
        """Compute HMAC and return digest (convenience method)."""
        self.set_hmac_key(key)
        return self.hash_data(data)
