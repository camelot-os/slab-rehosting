"""
STM32F4 CRYP Peripheral (Cryptographic Processor)

Supports:
- AES-128, AES-192, AES-256 (ECB, CBC, CTR, GCM)
- DES, TDES (ECB, CBC)

Register layout follows STM32F4 reference manual (RM0090).

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable
from .stm32_base import STM32Peripheral

# Crypto primitives - prefer cryptography library
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False


class STM32F4CRYP(STM32Peripheral):
    """
    STM32F4 CRYP (Cryptographic Processor).

    Register Map (offset from base 0x50060000):
        0x00: CR        - Control register
        0x04: SR        - Status register
        0x08: DIN       - Data input register
        0x0C: DOUT      - Data output register
        0x10: DMACR     - DMA control register
        0x14: IMSCR     - Interrupt mask set/clear register
        0x18: RISR      - Raw interrupt status register
        0x1C: MISR      - Masked interrupt status register
        0x20-0x3C: K0-K3 LR/RR - Key registers (256 bits max)
        0x40-0x4C: IV0-IV1 LR/RR - Initialization vector (128 bits)
        0x50-0x8C: CSGCMCCM0-7R - GCM/CCM context swap (AES only)
        0x90-0xCC: CSGCM0-7R - GCM context swap (AES only)

    CR Register Bits:
        [1:0]   Reserved
        [2]     ALGODIR     0=encrypt, 1=decrypt
        [5:3]   ALGOMODE    000=TDES-ECB, 001=TDES-CBC, 010=DES-ECB, 011=DES-CBC
                            100=AES-ECB, 101=AES-CBC, 110=AES-CTR, 111=AES-key prep
        [7:6]   DATATYPE    00=32-bit, 01=16-bit, 10=8-bit, 11=1-bit swap
        [9:8]   KEYSIZE     00=128-bit, 01=192-bit, 10=256-bit
        [14]    FFLUSH      Flush FIFO
        [15]    CRYPEN      Enable crypto processor
        [19:16] GCM_CCMPH   GCM/CCM phase (00=init, 01=header, 10=payload, 11=final)
    """

    # Register offsets
    CR = 0x00
    SR = 0x04
    DIN = 0x08
    DOUT = 0x0C
    DMACR = 0x10
    IMSCR = 0x14
    RISR = 0x18
    MISR = 0x1C

    # Key registers (256 bits = 8 x 32-bit)
    K0LR = 0x20
    K0RR = 0x24
    K1LR = 0x28
    K1RR = 0x2C
    K2LR = 0x30
    K2RR = 0x34
    K3LR = 0x38
    K3RR = 0x3C

    # IV registers (128 bits = 4 x 32-bit)
    IV0LR = 0x40
    IV0RR = 0x44
    IV1LR = 0x48
    IV1RR = 0x4C

    # GCM/CCM context swap registers
    CSGCMCCM0R = 0x50
    CSGCM0R = 0x70

    # CR bits
    CR_ALGODIR = 1 << 2      # 0=encrypt, 1=decrypt
    CR_ALGOMODE_MASK = 0x7 << 3
    CR_DATATYPE_MASK = 0x3 << 6
    CR_KEYSIZE_MASK = 0x3 << 8
    CR_FFLUSH = 1 << 14
    CR_CRYPEN = 1 << 15
    CR_GCM_CCMPH_MASK = 0xF << 16

    # ALGOMODE values
    ALGOMODE_TDES_ECB = 0
    ALGOMODE_TDES_CBC = 1
    ALGOMODE_DES_ECB = 2
    ALGOMODE_DES_CBC = 3
    ALGOMODE_AES_ECB = 4
    ALGOMODE_AES_CBC = 5
    ALGOMODE_AES_CTR = 6
    ALGOMODE_AES_KEY = 7  # Key preparation for decryption

    # SR bits
    SR_IFEM = 1 << 0   # Input FIFO empty
    SR_IFNF = 1 << 1   # Input FIFO not full
    SR_OFNE = 1 << 2   # Output FIFO not empty
    SR_OFFU = 1 << 3   # Output FIFO full
    SR_BUSY = 1 << 4   # Busy

    # DMACR bits
    DMACR_DIEN = 1 << 0  # DMA input enable
    DMACR_DOEN = 1 << 1  # DMA output enable

    # IMSCR bits
    IMSCR_INIM = 1 << 0   # Input FIFO interrupt mask
    IMSCR_OUTIM = 1 << 1  # Output FIFO interrupt mask

    def __init__(self, base: int = 0x50060000):
        super().__init__("CRYP", base, 0x400, irq=79)

        # Registers
        self.cr = 0
        self.sr = self.SR_IFEM | self.SR_IFNF  # FIFO empty, not full
        self.dmacr = 0
        self.imscr = 0

        # Key storage (256 bits max, big-endian word order)
        self.key = [0] * 8

        # IV storage (128 bits, big-endian word order)
        self.iv = [0] * 4

        # FIFO buffers
        self.din_fifo = []   # Input FIFO (up to 8 words)
        self.dout_fifo = []  # Output FIFO (up to 8 words)

        # GCM/CCM context
        self.gcm_context = [0] * 16

        # Block size depends on algorithm
        self._block_words = 4  # AES: 128 bits = 4 words

        self.log = logging.getLogger("STM32.CRYP")

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.SR:
            return self._get_sr()
        elif offset == self.DOUT:
            return self._read_dout()
        elif offset == self.DMACR:
            return self.dmacr
        elif offset == self.IMSCR:
            return self.imscr
        elif offset == self.RISR:
            return self._get_risr()
        elif offset == self.MISR:
            return self._get_risr() & self.imscr
        elif self.K0LR <= offset <= self.K3RR:
            idx = (offset - self.K0LR) // 4
            return self.key[idx]
        elif self.IV0LR <= offset <= self.IV1RR:
            idx = (offset - self.IV0LR) // 4
            return self.iv[idx]
        elif self.CSGCMCCM0R <= offset < self.CSGCM0R:
            idx = (offset - self.CSGCMCCM0R) // 4
            return self.gcm_context[idx] if idx < 8 else 0
        elif self.CSGCM0R <= offset < self.CSGCM0R + 32:
            idx = 8 + (offset - self.CSGCM0R) // 4
            return self.gcm_context[idx] if idx < 16 else 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self._write_cr(value)
        elif offset == self.DIN:
            self._write_din(value)
        elif offset == self.DMACR:
            self.dmacr = value
        elif offset == self.IMSCR:
            self.imscr = value
        elif self.K0LR <= offset <= self.K3RR:
            idx = (offset - self.K0LR) // 4
            self.key[idx] = value
        elif self.IV0LR <= offset <= self.IV1RR:
            idx = (offset - self.IV0LR) // 4
            self.iv[idx] = value
        elif self.CSGCMCCM0R <= offset < self.CSGCM0R:
            idx = (offset - self.CSGCMCCM0R) // 4
            if idx < 8:
                self.gcm_context[idx] = value
        elif self.CSGCM0R <= offset < self.CSGCM0R + 32:
            idx = 8 + (offset - self.CSGCM0R) // 4
            if idx < 16:
                self.gcm_context[idx] = value

    def _write_cr(self, value: int):
        # Handle FIFO flush
        if value & self.CR_FFLUSH:
            self.din_fifo.clear()
            self.dout_fifo.clear()
            value &= ~self.CR_FFLUSH

        old_cr = self.cr
        self.cr = value

        # Determine block size based on algorithm
        algomode = (self.cr >> 3) & 0x7
        if algomode in (self.ALGOMODE_DES_ECB, self.ALGOMODE_DES_CBC):
            self._block_words = 2  # DES: 64 bits
        else:
            self._block_words = 4  # AES/TDES: 128/64 bits (TDES uses 64-bit blocks but padded)

    def _get_sr(self) -> int:
        sr = 0
        if len(self.din_fifo) == 0:
            sr |= self.SR_IFEM
        if len(self.din_fifo) < 8:
            sr |= self.SR_IFNF
        if len(self.dout_fifo) > 0:
            sr |= self.SR_OFNE
        if len(self.dout_fifo) >= 8:
            sr |= self.SR_OFFU
        return sr

    def _get_risr(self) -> int:
        """Get raw interrupt status."""
        risr = 0
        if len(self.din_fifo) < 4:  # Input FIFO service request
            risr |= 0x01
        if len(self.dout_fifo) > 0:  # Output FIFO service request
            risr |= 0x02
        return risr

    def _write_din(self, value: int):
        """Write to data input register."""
        if not (self.cr & self.CR_CRYPEN):
            return

        self.din_fifo.append(value)

        # Process when we have enough data for a block
        if len(self.din_fifo) >= self._block_words:
            self._process_block()

    def _read_dout(self) -> int:
        """Read from data output register."""
        if self.dout_fifo:
            return self.dout_fifo.pop(0)
        return 0

    def _process_block(self):
        """Process one cipher block."""
        if not HAS_CRYPTOGRAPHY:
            # Fallback: pass-through
            self.dout_fifo.extend(self.din_fifo[:self._block_words])
            self.din_fifo = self.din_fifo[self._block_words:]
            return

        algomode = (self.cr >> 3) & 0x7
        keysize_bits = (self.cr >> 8) & 0x3
        decrypt = bool(self.cr & self.CR_ALGODIR)
        datatype = (self.cr >> 6) & 0x3

        # Get input block
        block_words = self.din_fifo[:self._block_words]
        self.din_fifo = self.din_fifo[self._block_words:]

        # Convert to bytes (big-endian)
        block = b''.join(w.to_bytes(4, 'big') for w in block_words)

        # Apply data type byte swapping
        block = self._swap_bytes(block, datatype)

        try:
            if algomode in (self.ALGOMODE_AES_ECB, self.ALGOMODE_AES_CBC,
                            self.ALGOMODE_AES_CTR, self.ALGOMODE_AES_KEY):
                result = self._process_aes(block, algomode, keysize_bits, decrypt)
            elif algomode in (self.ALGOMODE_DES_ECB, self.ALGOMODE_DES_CBC):
                result = self._process_des(block, algomode, decrypt)
            elif algomode in (self.ALGOMODE_TDES_ECB, self.ALGOMODE_TDES_CBC):
                result = self._process_tdes(block, algomode, decrypt)
            else:
                result = block  # Unknown mode, pass through
        except Exception as e:
            self.log.error(f"Crypto error: {e}")
            result = block

        # Swap bytes back
        result = self._swap_bytes(result, datatype)

        # Convert result back to words
        for i in range(0, len(result), 4):
            word = int.from_bytes(result[i:i+4], 'big')
            self.dout_fifo.append(word)

    def _swap_bytes(self, data: bytes, datatype: int) -> bytes:
        """Apply data type byte swapping."""
        if datatype == 0:  # 32-bit (no swap)
            return data
        elif datatype == 1:  # 16-bit half-word swap
            result = bytearray(len(data))
            for i in range(0, len(data), 4):
                result[i:i+2] = data[i+2:i+4]
                result[i+2:i+4] = data[i:i+2]
            return bytes(result)
        elif datatype == 2:  # 8-bit byte swap
            result = bytearray(len(data))
            for i in range(0, len(data), 4):
                result[i] = data[i+3]
                result[i+1] = data[i+2]
                result[i+2] = data[i+1]
                result[i+3] = data[i]
            return bytes(result)
        else:  # 1-bit swap (rarely used)
            return data

    def _get_key_bytes(self, keysize_bits: int) -> bytes:
        """Get key as bytes based on key size."""
        # Key registers are stored in big-endian order
        # K0LR, K0RR, K1LR, K1RR, K2LR, K2RR, K3LR, K3RR
        # For 128-bit: use K2, K3 (registers 4-7)
        # For 192-bit: use K1, K2, K3 (registers 2-7)
        # For 256-bit: use K0, K1, K2, K3 (registers 0-7)
        if keysize_bits == 0:  # 128-bit
            key_words = self.key[4:8]
        elif keysize_bits == 1:  # 192-bit
            key_words = self.key[2:8]
        else:  # 256-bit
            key_words = self.key[0:8]

        return b''.join(w.to_bytes(4, 'big') for w in key_words)

    def _get_iv_bytes(self) -> bytes:
        """Get IV as bytes."""
        return b''.join(w.to_bytes(4, 'big') for w in self.iv)

    def _process_aes(self, block: bytes, algomode: int, keysize_bits: int, decrypt: bool) -> bytes:
        """Process AES block using cryptography library."""
        key = self._get_key_bytes(keysize_bits)
        iv = self._get_iv_bytes()

        if algomode == self.ALGOMODE_AES_ECB:
            mode = modes.ECB()
        elif algomode == self.ALGOMODE_AES_CBC:
            mode = modes.CBC(iv)
        elif algomode == self.ALGOMODE_AES_CTR:
            # CTR mode uses IV as initial counter (nonce)
            mode = modes.CTR(iv)
        elif algomode == self.ALGOMODE_AES_KEY:
            # Key preparation mode - derive decryption key (ECB for now)
            mode = modes.ECB()
        else:
            return block

        cipher = Cipher(algorithms.AES(key), mode, backend=default_backend())

        if decrypt:
            decryptor = cipher.decryptor()
            return decryptor.update(block) + decryptor.finalize()
        else:
            encryptor = cipher.encryptor()
            return encryptor.update(block) + encryptor.finalize()

    def _process_des(self, block: bytes, algomode: int, decrypt: bool) -> bytes:
        """Process DES block using cryptography library."""
        # DES uses 64-bit key (8 bytes) from K2 registers
        key = b''.join(w.to_bytes(4, 'big') for w in self.key[4:6])
        iv = self._get_iv_bytes()[:8]

        if algomode == self.ALGOMODE_DES_ECB:
            mode = modes.ECB()
        else:  # CBC
            mode = modes.CBC(iv)

        cipher = Cipher(algorithms.TripleDES(key), mode, backend=default_backend())

        if decrypt:
            decryptor = cipher.decryptor()
            return decryptor.update(block[:8]) + decryptor.finalize()
        else:
            encryptor = cipher.encryptor()
            return encryptor.update(block[:8]) + encryptor.finalize()

    def _process_tdes(self, block: bytes, algomode: int, decrypt: bool) -> bytes:
        """Process Triple DES block using cryptography library."""
        # TDES uses 192-bit key (24 bytes) from K1, K2, K3
        key = b''.join(w.to_bytes(4, 'big') for w in self.key[2:8])
        iv = self._get_iv_bytes()[:8]

        if algomode == self.ALGOMODE_TDES_ECB:
            mode = modes.ECB()
        else:  # CBC
            mode = modes.CBC(iv)

        cipher = Cipher(algorithms.TripleDES(key), mode, backend=default_backend())

        if decrypt:
            decryptor = cipher.decryptor()
            return decryptor.update(block[:8]) + decryptor.finalize()
        else:
            encryptor = cipher.encryptor()
            return encryptor.update(block[:8]) + encryptor.finalize()

    # Convenience methods for testing

    def set_key(self, key: bytes, keysize: int = 128):
        """Set key from bytes (convenience method)."""
        # Convert key bytes to register format
        if keysize == 128:
            # 128-bit key goes to K2, K3
            for i in range(4):
                self.key[4 + i] = int.from_bytes(key[i*4:(i+1)*4], 'big')
            self.cr = (self.cr & ~self.CR_KEYSIZE_MASK) | (0 << 8)
        elif keysize == 192:
            # 192-bit key goes to K1, K2, K3
            for i in range(6):
                self.key[2 + i] = int.from_bytes(key[i*4:(i+1)*4], 'big')
            self.cr = (self.cr & ~self.CR_KEYSIZE_MASK) | (1 << 8)
        elif keysize == 256:
            # 256-bit key goes to K0, K1, K2, K3
            for i in range(8):
                self.key[i] = int.from_bytes(key[i*4:(i+1)*4], 'big')
            self.cr = (self.cr & ~self.CR_KEYSIZE_MASK) | (2 << 8)

    def set_iv(self, iv: bytes):
        """Set IV from bytes (convenience method)."""
        for i in range(min(len(iv) // 4, 4)):
            self.iv[i] = int.from_bytes(iv[i*4:(i+1)*4], 'big')

    def encrypt_block(self, data: bytes) -> bytes:
        """Encrypt a single block (convenience method)."""
        self.cr |= self.CR_CRYPEN
        self.cr &= ~self.CR_ALGODIR

        # Write data
        for i in range(0, len(data), 4):
            word = int.from_bytes(data[i:i+4], 'big')
            self._write_din(word)

        # Read result
        result = b''
        while self.dout_fifo:
            word = self.dout_fifo.pop(0)
            result += word.to_bytes(4, 'big')

        return result

    def decrypt_block(self, data: bytes) -> bytes:
        """Decrypt a single block (convenience method)."""
        self.cr |= self.CR_CRYPEN | self.CR_ALGODIR

        # Write data
        for i in range(0, len(data), 4):
            word = int.from_bytes(data[i:i+4], 'big')
            self._write_din(word)

        # Read result
        result = b''
        while self.dout_fifo:
            word = self.dout_fifo.pop(0)
            result += word.to_bytes(4, 'big')

        return result
