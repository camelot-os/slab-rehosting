"""
NRF Crypto Peripherals - ECB and CCM

Uses Python cryptography library for actual crypto operations.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable
from .nrf_base import NRFPeripheral

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class NRFECB(NRFPeripheral):
    """
    NRF AES-128 ECB Encryption.

    Uses cryptography library for actual AES operations.
    """

    TASKS_STARTECB = 0x000
    TASKS_STOPECB = 0x004
    EVENTS_ENDECB = 0x100
    EVENTS_ERRORECB = 0x104
    ECBDATAPTR = 0x504

    def __init__(self, base: int = 0x4000E000):
        super().__init__("ECB", base, 0x1000, irq=14)

        self.ecbdataptr = 0
        self.mem_read: Optional[Callable[[int, int], bytes]] = None
        self.mem_write: Optional[Callable[[int, bytes], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ECBDATAPTR:
            return self.ecbdataptr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ECBDATAPTR:
            self.ecbdataptr = value

    def _handle_task(self, offset: int):
        if offset == self.TASKS_STARTECB:
            self._do_ecb()
        elif offset == self.TASKS_STOPECB:
            pass

    def _do_ecb(self):
        """Perform AES-128 ECB encryption."""
        if not self.mem_read or not self.mem_write:
            self.set_event(self.EVENTS_ERRORECB)
            return

        # ECB data structure: key[16], cleartext[16], ciphertext[16]
        data = self.mem_read(self.ecbdataptr, 48)
        if len(data) < 32:
            self.set_event(self.EVENTS_ERRORECB)
            return

        key = bytes(data[:16])
        cleartext = bytes(data[16:32])

        if HAS_CRYPTO:
            cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
            encryptor = cipher.encryptor()
            ciphertext = encryptor.update(cleartext) + encryptor.finalize()
        else:
            # Fallback: XOR with key (not secure, just for basic testing)
            ciphertext = bytes(c ^ k for c, k in zip(cleartext, key))

        # Write ciphertext back
        self.mem_write(self.ecbdataptr + 32, ciphertext)
        self.set_event(self.EVENTS_ENDECB)

    # Convenience method
    def encrypt(self, key: bytes, plaintext: bytes) -> bytes:
        """Encrypt plaintext with AES-128 ECB (convenience method)."""
        if len(key) != 16 or len(plaintext) != 16:
            raise ValueError("Key and plaintext must be 16 bytes")

        if HAS_CRYPTO:
            cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
            encryptor = cipher.encryptor()
            return encryptor.update(plaintext) + encryptor.finalize()
        else:
            # Fallback: XOR with key (not secure, just for basic testing)
            return bytes(c ^ k for c, k in zip(plaintext, key))


class NRFCCM(NRFPeripheral):
    """
    NRF AES-128 CCM Mode (Counter with CBC-MAC).

    Used for BLE encryption.
    """

    TASKS_KSGEN = 0x000
    TASKS_CRYPT = 0x004
    TASKS_STOP = 0x008
    TASKS_RATEOVERRIDE = 0x00C
    EVENTS_ENDKSGEN = 0x100
    EVENTS_ENDCRYPT = 0x104
    EVENTS_ERROR = 0x108

    ENABLE = 0x500
    MODE = 0x504
    CNFPTR = 0x508
    INPTR = 0x50C
    OUTPTR = 0x510
    SCRATCHPTR = 0x514
    MAXPACKETSIZE = 0x518
    RATEOVERRIDE = 0x51C
    HEADERMASK = 0x520

    def __init__(self, base: int = 0x4000F000):
        super().__init__("CCM", base, 0x1000, irq=15)

        self.enable = 0
        self.mode = 0  # 0=encrypt, 1=decrypt
        self.cnfptr = 0
        self.inptr = 0
        self.outptr = 0
        self.scratchptr = 0
        self.maxpacketsize = 0xFB
        self.headermask = 0xE3

        self.mem_read: Optional[Callable[[int, int], bytes]] = None
        self.mem_write: Optional[Callable[[int, bytes], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        regs = {
            self.ENABLE: self.enable,
            self.MODE: self.mode,
            self.CNFPTR: self.cnfptr,
            self.INPTR: self.inptr,
            self.OUTPTR: self.outptr,
            self.SCRATCHPTR: self.scratchptr,
            self.MAXPACKETSIZE: self.maxpacketsize,
            self.HEADERMASK: self.headermask,
        }
        return regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ENABLE:
            self.enable = value & 0x3
        elif offset == self.MODE:
            self.mode = value
        elif offset == self.CNFPTR:
            self.cnfptr = value
        elif offset == self.INPTR:
            self.inptr = value
        elif offset == self.OUTPTR:
            self.outptr = value
        elif offset == self.SCRATCHPTR:
            self.scratchptr = value
        elif offset == self.MAXPACKETSIZE:
            self.maxpacketsize = value
        elif offset == self.HEADERMASK:
            self.headermask = value

    def _handle_task(self, offset: int):
        if offset == self.TASKS_KSGEN:
            self._generate_keystream()
        elif offset == self.TASKS_CRYPT:
            self._do_crypt()
        elif offset == self.TASKS_STOP:
            pass

    def _generate_keystream(self):
        """Generate keystream for CCM."""
        # Simplified - actual implementation needs CCM mode
        self.set_event(self.EVENTS_ENDKSGEN)

    def _do_crypt(self):
        """Perform CCM encryption/decryption."""
        if not self.mem_read or not self.mem_write:
            self.set_event(self.EVENTS_ERROR)
            return

        # Read configuration (key, nonce, etc.)
        # For BLE: CNFPTR points to 33-byte structure
        # Simplified implementation
        self.set_event(self.EVENTS_ENDCRYPT)
