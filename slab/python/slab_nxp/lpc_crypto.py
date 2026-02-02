"""
LPC55xx Crypto Peripherals - CASPER, HASHCRYPT, PUF

Uses Python cryptography library for actual crypto operations.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import secrets
import hashlib
from typing import Optional, Callable
from .nxp_base import NXPPeripheral

# Try to import cryptography for AES
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class LPCCASPER(NXPPeripheral):
    """
    LPC55xx CASPER - Cryptographic Accelerator for RSA/ECC.

    Features:
    - Hardware acceleration for modular arithmetic
    - RSA up to 4096 bits
    - ECC NIST P-256, P-384, P-521
    - Uses dedicated SRAM for operands

    Memory Map:
        0x00: CTRL0 - Control 0
        0x04: CTRL1 - Control 1
        0x08: LOADER - Loader
        0x0C: STATUS - Status
        0x10: INTENSET - Interrupt enable set
        0x14: INTENCLR - Interrupt enable clear
        0x18: INTSTAT - Interrupt status
        0x40: AREG - A register pointer
        0x44: BREG - B register pointer
        0x48: CREG - C register pointer
        0x4C: DREG - D register pointer
        0x50: RES0-3 - Result registers
        0x60: MASK - Mask
        0x64: REMASK - Remask
        0x68: LOCK - Lock
    """

    CTRL0 = 0x00
    CTRL1 = 0x04
    LOADER = 0x08
    STATUS = 0x0C
    INTENSET = 0x10
    INTENCLR = 0x14
    INTSTAT = 0x18
    AREG = 0x40
    BREG = 0x44
    CREG = 0x48
    DREG = 0x4C
    RES0 = 0x50
    RES1 = 0x54
    RES2 = 0x58
    RES3 = 0x5C
    MASK = 0x60
    REMASK = 0x64
    LOCK = 0x68

    # CTRL0 bits
    CTRL0_ABBPAIR = (0x03 << 0)
    CTRL0_CTRLB_EN = (1 << 16)

    # STATUS bits
    STATUS_DONE = (1 << 0)
    STATUS_CARRY = (1 << 4)

    def __init__(self, base: int = 0x400A5000):
        super().__init__("CASPER", base, 0x1000)

        self.ctrl0 = 0
        self.ctrl1 = 0
        self.loader = 0
        self.status = self.STATUS_DONE
        self.intenset = 0
        self.intstat = 0

        self.areg = 0
        self.breg = 0
        self.creg = 0
        self.dreg = 0
        self.res = [0, 0, 0, 0]
        self.mask = 0
        self.remask = 0
        self.lock = 0

        # Callback to access CASPER SRAM
        self.read_memory: Optional[Callable[[int, int], bytes]] = None
        self.write_memory: Optional[Callable[[int, bytes], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CTRL0:
            return self.ctrl0
        elif offset == self.CTRL1:
            return self.ctrl1
        elif offset == self.LOADER:
            return self.loader
        elif offset == self.STATUS:
            return self.status
        elif offset == self.INTENSET:
            return self.intenset
        elif offset == self.INTENCLR:
            return 0
        elif offset == self.INTSTAT:
            return self.intstat
        elif offset == self.AREG:
            return self.areg
        elif offset == self.BREG:
            return self.breg
        elif offset == self.CREG:
            return self.creg
        elif offset == self.DREG:
            return self.dreg
        elif offset == self.RES0:
            return self.res[0]
        elif offset == self.RES1:
            return self.res[1]
        elif offset == self.RES2:
            return self.res[2]
        elif offset == self.RES3:
            return self.res[3]
        elif offset == self.MASK:
            return self.mask
        elif offset == self.REMASK:
            return self.remask
        elif offset == self.LOCK:
            return self.lock
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL0:
            self.ctrl0 = value
            self._execute_operation()
        elif offset == self.CTRL1:
            self.ctrl1 = value
        elif offset == self.LOADER:
            self.loader = value
        elif offset == self.INTENSET:
            self.intenset |= value
        elif offset == self.INTENCLR:
            self.intenset &= ~value
        elif offset == self.INTSTAT:
            self.intstat &= ~value
        elif offset == self.AREG:
            self.areg = value
        elif offset == self.BREG:
            self.breg = value
        elif offset == self.CREG:
            self.creg = value
        elif offset == self.DREG:
            self.dreg = value
        elif offset == self.MASK:
            self.mask = value
        elif offset == self.REMASK:
            self.remask = value
        elif offset == self.LOCK:
            self.lock = value

    def _execute_operation(self):
        """Execute CASPER operation (simplified)."""
        # CASPER operations are complex modular arithmetic
        # Full implementation would require proper big integer math
        # For now, mark as done immediately
        self.status = self.STATUS_DONE
        self.intstat |= 1
        if self.intenset & 1:
            self.trigger_irq(1)


class LPCHASHCRYPT(NXPPeripheral):
    """
    LPC55xx HASHCRYPT - AES and Hash Engine.

    Features:
    - AES-128/192/256 ECB/CBC/CTR
    - SHA-1, SHA-256
    - Hardware key support
    - DMA compatible

    Memory Map:
        0x00: CTRL - Control
        0x04: STATUS - Status
        0x08: INTENSET - Interrupt enable set
        0x0C: INTENCLR - Interrupt enable clear
        0x10: MEMCTRL - Memory control
        0x14: MEMADDR - Memory address
        0x40: INDATA - Input data
        0x50: ALIAS[0-6] - Input data aliases
        0x80: DIGEST0-7 - Hash digest / AES output
        0xC0: CRYPTCFG - Crypto configuration
        0xC4: CONFIG - Configuration
        0xD0: LOCK - Lock
        0xE0: MASK[0-3] - Key mask
    """

    CTRL = 0x00
    STATUS = 0x04
    INTENSET = 0x08
    INTENCLR = 0x0C
    MEMCTRL = 0x10
    MEMADDR = 0x14
    INDATA = 0x40
    ALIAS_BASE = 0x50
    DIGEST_BASE = 0x80
    CRYPTCFG = 0xC0
    CONFIG = 0xC4
    LOCK = 0xD0
    MASK_BASE = 0xE0

    # CTRL bits
    CTRL_MODE_MASK = 0x07
    CTRL_MODE_DISABLED = 0
    CTRL_MODE_SHA1 = 1
    CTRL_MODE_SHA256 = 2
    CTRL_MODE_AES = 4
    CTRL_NEW_HASH = (1 << 4)

    # STATUS bits
    STATUS_WAITING = (1 << 0)
    STATUS_DIGEST_READY = (1 << 1)
    STATUS_ERROR = (1 << 2)

    # CRYPTCFG bits
    CRYPTCFG_AESMODE_MASK = 0x03
    CRYPTCFG_AESMODE_ECB = 0
    CRYPTCFG_AESMODE_CBC = 1
    CRYPTCFG_AESMODE_CTR = 2
    CRYPTCFG_AESDECRYPT = (1 << 4)
    CRYPTCFG_AESSECRET = (1 << 8)
    CRYPTCFG_AESKEYSZ_MASK = (0x03 << 16)
    CRYPTCFG_AESKEYSZ_128 = (0 << 16)
    CRYPTCFG_AESKEYSZ_192 = (1 << 16)
    CRYPTCFG_AESKEYSZ_256 = (2 << 16)

    def __init__(self, base: int = 0x400A4000):
        super().__init__("HASHCRYPT", base, 0x1000)

        self.ctrl = 0
        self.status = self.STATUS_WAITING
        self.intenset = 0
        self.memctrl = 0
        self.memaddr = 0
        self.cryptcfg = 0
        self.config = 0
        self.lock = 0

        # Key and IV
        self.key = bytearray(32)
        self.iv = bytearray(16)
        self.mask = [0, 0, 0, 0]

        # Digest output (8 x 32-bit)
        self.digest = [0] * 8

        # Hash state
        self._hash_ctx = None
        self._hash_buffer = bytearray()

        # AES cipher
        self._cipher = None

        # Memory access callback
        self.read_memory: Optional[Callable[[int, int], bytes]] = None

    def _init_hash(self, mode: int):
        """Initialize hash context."""
        if mode == self.CTRL_MODE_SHA1:
            self._hash_ctx = hashlib.sha1()
        elif mode == self.CTRL_MODE_SHA256:
            self._hash_ctx = hashlib.sha256()
        else:
            self._hash_ctx = None
        self._hash_buffer.clear()

    def _update_hash(self, data: bytes):
        """Update hash with data."""
        if self._hash_ctx:
            self._hash_ctx.update(data)

    def _finalize_hash(self):
        """Finalize hash and store digest."""
        if self._hash_ctx:
            digest_bytes = self._hash_ctx.digest()
            # Store in digest registers (big-endian)
            for i in range(min(8, len(digest_bytes) // 4)):
                self.digest[i] = int.from_bytes(
                    digest_bytes[i*4:(i+1)*4], 'big'
                )
            self.status |= self.STATUS_DIGEST_READY

    def _init_aes(self):
        """Initialize AES cipher."""
        if not HAS_CRYPTO:
            self.log.warning("cryptography library not available for AES")
            return

        keysz = (self.cryptcfg & self.CRYPTCFG_AESKEYSZ_MASK) >> 16
        key_len = [16, 24, 32][keysz]
        key = bytes(self.key[:key_len])

        aes_mode = self.cryptcfg & self.CRYPTCFG_AESMODE_MASK
        if aes_mode == self.CRYPTCFG_AESMODE_ECB:
            mode = modes.ECB()
        elif aes_mode == self.CRYPTCFG_AESMODE_CBC:
            mode = modes.CBC(bytes(self.iv))
        elif aes_mode == self.CRYPTCFG_AESMODE_CTR:
            mode = modes.CTR(bytes(self.iv))
        else:
            return

        cipher = Cipher(algorithms.AES(key), mode, backend=default_backend())
        if self.cryptcfg & self.CRYPTCFG_AESDECRYPT:
            self._cipher = cipher.decryptor()
        else:
            self._cipher = cipher.encryptor()

    def _process_aes_block(self, data: bytes) -> bytes:
        """Process AES block."""
        if self._cipher:
            return self._cipher.update(data)
        return data

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CTRL:
            return self.ctrl
        elif offset == self.STATUS:
            return self.status
        elif offset == self.INTENSET:
            return self.intenset
        elif offset == self.MEMCTRL:
            return self.memctrl
        elif offset == self.MEMADDR:
            return self.memaddr
        elif offset == self.CRYPTCFG:
            return self.cryptcfg
        elif offset == self.CONFIG:
            return self.config
        elif offset == self.LOCK:
            return self.lock
        elif self.DIGEST_BASE <= offset < self.DIGEST_BASE + 32:
            idx = (offset - self.DIGEST_BASE) // 4
            return self.digest[idx]
        elif self.MASK_BASE <= offset < self.MASK_BASE + 16:
            idx = (offset - self.MASK_BASE) // 4
            return self.mask[idx]
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            old_ctrl = self.ctrl
            self.ctrl = value

            mode = value & self.CTRL_MODE_MASK
            if value & self.CTRL_NEW_HASH:
                self._init_hash(mode)
            elif mode == self.CTRL_MODE_AES:
                self._init_aes()

        elif offset == self.STATUS:
            # Write 1 to clear
            self.status &= ~(value & 0x07)
        elif offset == self.INTENSET:
            self.intenset |= value
        elif offset == self.INTENCLR:
            self.intenset &= ~value
        elif offset == self.MEMCTRL:
            self.memctrl = value
            if value & 0x01:  # Start
                self._process_memory()
        elif offset == self.MEMADDR:
            self.memaddr = value
        elif offset == self.CRYPTCFG:
            self.cryptcfg = value
        elif offset == self.CONFIG:
            self.config = value
        elif offset == self.LOCK:
            self.lock = value
        elif offset == self.INDATA or (self.ALIAS_BASE <= offset < self.ALIAS_BASE + 28):
            # Input data - process block
            self._process_input(value)
        elif self.MASK_BASE <= offset < self.MASK_BASE + 16:
            idx = (offset - self.MASK_BASE) // 4
            self.mask[idx] = value

    def _process_input(self, value: int):
        """Process input word."""
        mode = self.ctrl & self.CTRL_MODE_MASK

        if mode in (self.CTRL_MODE_SHA1, self.CTRL_MODE_SHA256):
            # Add to hash buffer
            self._hash_buffer.extend(value.to_bytes(4, 'little'))
            if len(self._hash_buffer) >= 64:
                self._update_hash(bytes(self._hash_buffer[:64]))
                self._hash_buffer = self._hash_buffer[64:]
                self.status |= self.STATUS_WAITING
        elif mode == self.CTRL_MODE_AES:
            # Process AES
            data = value.to_bytes(4, 'little')
            # AES needs 16-byte blocks, accumulate
            pass

    def _process_memory(self):
        """Process data from memory."""
        if not self.read_memory:
            return

        count = (self.memctrl >> 16) & 0x7FF
        if count == 0:
            return

        data = self.read_memory(self.memaddr, count * 4)
        mode = self.ctrl & self.CTRL_MODE_MASK

        if mode in (self.CTRL_MODE_SHA1, self.CTRL_MODE_SHA256):
            self._update_hash(data)
            self._finalize_hash()
        elif mode == self.CTRL_MODE_AES:
            result = self._process_aes_block(data)
            # Store result in digest registers
            for i in range(min(4, len(result) // 4)):
                self.digest[i] = int.from_bytes(result[i*4:(i+1)*4], 'little')

        self.status |= self.STATUS_DIGEST_READY
        if self.intenset & 0x02:
            self.trigger_irq(1)


class LPCPUF(NXPPeripheral):
    """
    LPC55xx PUF - Physical Unclonable Function.

    Features:
    - Generates device-unique keys from SRAM startup pattern
    - Key codes for secure key storage
    - Intrinsic ID

    Memory Map:
        0x00: CTRL - Control
        0x04: KEYINDEX - Key index
        0x08: KEYSIZE - Key size
        0x10: STAT - Status
        0x18: ALLOW - Allow register
        0x1C: Reserved
        0x30: KEYINPUT - Key input
        0x34: CODEINPUT - Code input
        0x38: CODEOUTPUT - Code output
        0x40: Reserved
        0x4C: KEYOUTINDEX - Key output index
        0x50: KEYOUTPUT - Key output
        0xA0: IFSTAT - Interface status
        0xB0: VERSION - Version
        0xD0: INTEN - Interrupt enable
        0xD4: INTSTAT - Interrupt status
        0xD8: PWRCTRL - Power control
        0xDC: CFG - Configuration
    """

    CTRL = 0x00
    KEYINDEX = 0x04
    KEYSIZE = 0x08
    STAT = 0x10
    ALLOW = 0x18
    KEYINPUT = 0x30
    CODEINPUT = 0x34
    CODEOUTPUT = 0x38
    KEYOUTINDEX = 0x4C
    KEYOUTPUT = 0x50
    IFSTAT = 0xA0
    VERSION = 0xB0
    INTEN = 0xD0
    INTSTAT = 0xD4
    PWRCTRL = 0xD8
    CFG = 0xDC

    # CTRL commands
    CTRL_ENROLL = 0x01
    CTRL_START = 0x02
    CTRL_GENERATEKEY = 0x04
    CTRL_SETKEY = 0x08
    CTRL_GETKEY = 0x10
    CTRL_ZEROIZE = 0x20

    # STAT bits
    STAT_BUSY = (1 << 0)
    STAT_SUCCESS = (1 << 1)
    STAT_ERROR = (1 << 2)
    STAT_KEYINREQ = (1 << 4)
    STAT_KEYOUTAVAIL = (1 << 5)
    STAT_CODEINREQ = (1 << 6)
    STAT_CODEOUTAVAIL = (1 << 7)

    def __init__(self, base: int = 0x4003B000):
        super().__init__("PUF", base, 0x1000)

        self.ctrl = 0
        self.keyindex = 0
        self.keysize = 0
        self.stat = 0
        self.allow = 0
        self.keyoutindex = 0
        self.ifstat = 0
        self.inten = 0
        self.intstat = 0
        self.pwrctrl = 0
        self.cfg = 0

        # Simulated PUF state
        self._enrolled = False
        self._activation_code = bytearray(1192)  # Typical AC size
        self._key_codes = {}  # index -> key code
        self._current_key = bytearray(32)

        # Unique device ID (simulated from random on first use)
        self._device_seed = secrets.token_bytes(32)

    def _derive_key(self, index: int, size: int) -> bytes:
        """Derive a key from PUF (simulated)."""
        # Use HKDF-like derivation
        h = hashlib.sha256()
        h.update(self._device_seed)
        h.update(index.to_bytes(4, 'little'))
        h.update(size.to_bytes(4, 'little'))
        return h.digest()[:size]

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CTRL:
            return self.ctrl
        elif offset == self.KEYINDEX:
            return self.keyindex
        elif offset == self.KEYSIZE:
            return self.keysize
        elif offset == self.STAT:
            return self.stat
        elif offset == self.ALLOW:
            return self.allow
        elif offset == self.KEYOUTINDEX:
            return self.keyoutindex
        elif offset == self.KEYOUTPUT:
            if self.stat & self.STAT_KEYOUTAVAIL:
                # Return next key word
                idx = self.keyoutindex
                if idx < len(self._current_key) // 4:
                    val = int.from_bytes(
                        self._current_key[idx*4:(idx+1)*4], 'little'
                    )
                    self.keyoutindex += 1
                    if self.keyoutindex >= self.keysize // 4:
                        self.stat &= ~self.STAT_KEYOUTAVAIL
                    return val
            return 0
        elif offset == self.CODEOUTPUT:
            if self.stat & self.STAT_CODEOUTAVAIL:
                return 0x12345678  # Placeholder key code word
            return 0
        elif offset == self.IFSTAT:
            return self.ifstat
        elif offset == self.VERSION:
            return 0x00010001  # Version 1.1
        elif offset == self.INTEN:
            return self.inten
        elif offset == self.INTSTAT:
            return self.intstat
        elif offset == self.PWRCTRL:
            return self.pwrctrl
        elif offset == self.CFG:
            return self.cfg
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            self._handle_command(value)
        elif offset == self.KEYINDEX:
            self.keyindex = value & 0x0F
        elif offset == self.KEYSIZE:
            self.keysize = value & 0x3F
        elif offset == self.ALLOW:
            self.allow = value
        elif offset == self.KEYINPUT:
            if self.stat & self.STAT_KEYINREQ:
                # Accept key input
                pass
        elif offset == self.CODEINPUT:
            if self.stat & self.STAT_CODEINREQ:
                # Accept code input
                pass
        elif offset == self.IFSTAT:
            self.ifstat &= ~value  # W1C
        elif offset == self.INTEN:
            self.inten = value
        elif offset == self.INTSTAT:
            self.intstat &= ~value  # W1C
        elif offset == self.PWRCTRL:
            self.pwrctrl = value
        elif offset == self.CFG:
            self.cfg = value

    def _handle_command(self, cmd: int):
        """Handle PUF command."""
        self.ctrl = cmd
        self.stat |= self.STAT_BUSY

        if cmd & self.CTRL_ENROLL:
            # Enroll - generate activation code
            self._enrolled = True
            self._activation_code = secrets.token_bytes(1192)
            self.stat = self.STAT_SUCCESS | self.STAT_CODEOUTAVAIL

        elif cmd & self.CTRL_START:
            # Start - reconstruct from activation code
            if self._enrolled:
                self.stat = self.STAT_SUCCESS
            else:
                self.stat = self.STAT_ERROR

        elif cmd & self.CTRL_GENERATEKEY:
            # Generate key and key code
            key_bytes = self.keysize if self.keysize else 16
            self._current_key = bytearray(self._derive_key(self.keyindex, key_bytes))
            self.keyoutindex = 0
            self.stat = self.STAT_SUCCESS | self.STAT_KEYOUTAVAIL | self.STAT_CODEOUTAVAIL

        elif cmd & self.CTRL_SETKEY:
            # Set user key (wrap with key code)
            self.stat = self.STAT_KEYINREQ

        elif cmd & self.CTRL_GETKEY:
            # Get key from key code
            key_bytes = self.keysize if self.keysize else 16
            self._current_key = bytearray(self._derive_key(self.keyindex, key_bytes))
            self.keyoutindex = 0
            self.stat = self.STAT_SUCCESS | self.STAT_KEYOUTAVAIL

        elif cmd & self.CTRL_ZEROIZE:
            # Zeroize all key material
            self._current_key = bytearray(32)
            self._key_codes.clear()
            self.stat = self.STAT_SUCCESS

        if self.inten and self.stat & self.STAT_SUCCESS:
            self.intstat |= 1
            self.trigger_irq(1)
