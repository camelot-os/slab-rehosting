#!/usr/bin/env python3
"""
MCUemu Peripheral Bridges

This module provides bridges between emulated MCU peripherals and real host
capabilities:

1. CryptoEngine: STM32F4 CRYP/HASH -> OpenSSL
2. CANBridge: CAN controller -> SocketCAN/Scapy
3. BluetoothBridge: BLE controller -> HCI/BlueZ

These bridges enable:
- Hardware-accurate crypto operations using OpenSSL
- Real CAN bus communication via SocketCAN
- Bluetooth communication via HCI dongles

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Tuple
from enum import IntEnum, IntFlag
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger('Bridges')

# Thread pool for blocking operations
_bridge_executor: Optional[ThreadPoolExecutor] = None

def get_bridge_executor() -> ThreadPoolExecutor:
    global _bridge_executor
    if _bridge_executor is None:
        _bridge_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bridge")
    return _bridge_executor


# =============================================================================
# STM32F4 CRYPTO ENGINE -> OPENSSL
# =============================================================================

class STM32CryptoAlgorithm(IntEnum):
    """CRYP algorithm selection (CR.ALGOMODE)."""
    TDES_ECB = 0b000
    TDES_CBC = 0b001
    DES_ECB = 0b010
    DES_CBC = 0b011
    AES_ECB = 0b100
    AES_CBC = 0b101
    AES_CTR = 0b110
    AES_KEY = 0b111  # Key preparation for GCM/CCM


class STM32CryptoDirection(IntEnum):
    """Encryption/Decryption direction."""
    ENCRYPT = 0
    DECRYPT = 1


@dataclass
class CryptoContext:
    """Crypto operation context."""
    algorithm: STM32CryptoAlgorithm = STM32CryptoAlgorithm.AES_ECB
    direction: STM32CryptoDirection = STM32CryptoDirection.ENCRYPT
    key_size: int = 128  # 128, 192, or 256 bits
    key: bytes = b''
    iv: bytes = b''
    data_type: int = 0  # 0=32bit, 1=16bit, 2=8bit, 3=1bit


class STM32CryptoEngine:
    """
    STM32F4 CRYP peripheral bridge to OpenSSL.

    Maps STM32F4 CRYP hardware crypto accelerator to OpenSSL operations.
    Supports AES, DES, and TDES in various modes.

    Register Map (0x50060000):
        CR      0x00    Control register
        SR      0x04    Status register
        DIN     0x08    Data input register
        DOUT    0x0C    Data output register
        DMACR   0x10    DMA control register
        IMSCR   0x14    Interrupt mask set/clear
        RISR    0x18    Raw interrupt status
        MISR    0x1C    Masked interrupt status
        K0LR    0x20    Key registers (K0-K3, left/right)
        K0RR    0x24
        ...
        IV0LR   0x40    IV registers
        IV0RR   0x44
        IV1LR   0x48
        IV1RR   0x4C
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
    K0LR = 0x20
    K0RR = 0x24
    K1LR = 0x28
    K1RR = 0x2C
    K2LR = 0x30
    K2RR = 0x34
    K3LR = 0x38
    K3RR = 0x3C
    IV0LR = 0x40
    IV0RR = 0x44
    IV1LR = 0x48
    IV1RR = 0x4C

    # CR bits
    CR_ALGODIR = (1 << 2)      # Direction: 0=encrypt, 1=decrypt
    CR_ALGOMODE = (7 << 3)     # Algorithm mode
    CR_DATATYPE = (3 << 6)     # Data type
    CR_KEYSIZE = (3 << 8)      # Key size
    CR_FFLUSH = (1 << 14)      # FIFO flush
    CR_CRYPEN = (1 << 15)      # Crypto enable

    # SR bits
    SR_IFEM = (1 << 0)   # Input FIFO empty
    SR_IFNF = (1 << 1)   # Input FIFO not full
    SR_OFNE = (1 << 2)   # Output FIFO not empty
    SR_OFFU = (1 << 3)   # Output FIFO full
    SR_BUSY = (1 << 4)   # Busy

    def __init__(self, base: int = 0x50060000):
        self.base = base
        self.size = 0x400
        self.log = logging.getLogger('CRYP')

        # Registers
        self.cr = 0
        self.sr = self.SR_IFEM | self.SR_IFNF  # Empty, not full
        self.dmacr = 0
        self.imscr = 0

        # Key registers (256 bits max)
        self.key_regs = [0] * 8  # K0LR, K0RR, K1LR, K1RR, K2LR, K2RR, K3LR, K3RR

        # IV registers (128 bits)
        self.iv_regs = [0] * 4  # IV0LR, IV0RR, IV1LR, IV1RR

        # FIFOs
        self.input_fifo: List[int] = []
        self.output_fifo: List[int] = []

        # OpenSSL cipher context
        self._cipher = None
        self._openssl_available = self._check_openssl()

    def _check_openssl(self) -> bool:
        """Check if OpenSSL/cryptography is available."""
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend
            self.log.info("OpenSSL backend available via cryptography library")
            return True
        except ImportError:
            self.log.warning("cryptography library not available, using fallback")
            return False

    def read(self, offset: int, size: int) -> int:
        """Read register."""
        if offset == self.CR:
            return self.cr
        elif offset == self.SR:
            return self._get_status()
        elif offset == self.DOUT:
            return self._read_output()
        elif offset == self.DMACR:
            return self.dmacr
        elif offset == self.IMSCR:
            return self.imscr
        elif self.K0LR <= offset <= self.K3RR:
            idx = (offset - self.K0LR) // 4
            return self.key_regs[idx]
        elif self.IV0LR <= offset <= self.IV1RR:
            idx = (offset - self.IV0LR) // 4
            return self.iv_regs[idx]
        return 0

    def write(self, offset: int, size: int, value: int):
        """Write register."""
        if offset == self.CR:
            self._write_cr(value)
        elif offset == self.DIN:
            self._write_input(value)
        elif offset == self.DMACR:
            self.dmacr = value
        elif offset == self.IMSCR:
            self.imscr = value
        elif self.K0LR <= offset <= self.K3RR:
            idx = (offset - self.K0LR) // 4
            self.key_regs[idx] = value
            self.log.debug(f"Key[{idx}] = 0x{value:08X}")
        elif self.IV0LR <= offset <= self.IV1RR:
            idx = (offset - self.IV0LR) // 4
            self.iv_regs[idx] = value
            self.log.debug(f"IV[{idx}] = 0x{value:08X}")

    def _write_cr(self, value: int):
        """Write control register."""
        old_cr = self.cr
        self.cr = value

        # FIFO flush
        if value & self.CR_FFLUSH:
            self.input_fifo.clear()
            self.output_fifo.clear()
            self.cr &= ~self.CR_FFLUSH

        # Crypto enable
        if (value & self.CR_CRYPEN) and not (old_cr & self.CR_CRYPEN):
            self._init_cipher()
            self.log.info("Crypto engine enabled")

    def _init_cipher(self):
        """Initialize OpenSSL cipher based on CR settings."""
        if not self._openssl_available:
            return

        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend

        # Extract settings from CR
        algo_mode = (self.cr >> 3) & 0x7
        direction = (self.cr >> 2) & 0x1
        key_size_bits = [128, 192, 256][(self.cr >> 8) & 0x3]

        # Build key from registers
        key_bytes = key_size_bits // 8
        key = b''
        for i in range(key_bytes // 4):
            key += struct.pack('>I', self.key_regs[i])

        # Build IV from registers
        iv = struct.pack('>IIII',
            self.iv_regs[0], self.iv_regs[1],
            self.iv_regs[2], self.iv_regs[3]
        )

        self.log.debug(f"Init cipher: algo={algo_mode} dir={direction} keysize={key_size_bits}")
        self.log.debug(f"Key: {key.hex()}")
        self.log.debug(f"IV: {iv.hex()}")

        # Select algorithm and mode
        try:
            if algo_mode == STM32CryptoAlgorithm.AES_ECB:
                cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
            elif algo_mode == STM32CryptoAlgorithm.AES_CBC:
                cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            elif algo_mode == STM32CryptoAlgorithm.AES_CTR:
                cipher = Cipher(algorithms.AES(key), modes.CTR(iv), backend=default_backend())
            elif algo_mode == STM32CryptoAlgorithm.DES_ECB:
                cipher = Cipher(algorithms.TripleDES(key[:8]), modes.ECB(), backend=default_backend())
            elif algo_mode == STM32CryptoAlgorithm.DES_CBC:
                cipher = Cipher(algorithms.TripleDES(key[:8]), modes.CBC(iv[:8]), backend=default_backend())
            elif algo_mode == STM32CryptoAlgorithm.TDES_ECB:
                cipher = Cipher(algorithms.TripleDES(key[:24]), modes.ECB(), backend=default_backend())
            elif algo_mode == STM32CryptoAlgorithm.TDES_CBC:
                cipher = Cipher(algorithms.TripleDES(key[:24]), modes.CBC(iv[:8]), backend=default_backend())
            else:
                self.log.warning(f"Unsupported algorithm mode: {algo_mode}")
                return

            if direction == STM32CryptoDirection.ENCRYPT:
                self._cipher = cipher.encryptor()
            else:
                self._cipher = cipher.decryptor()

        except Exception as e:
            self.log.error(f"Cipher init failed: {e}")
            self._cipher = None

    def _write_input(self, value: int):
        """Write data to input FIFO."""
        self.input_fifo.append(value)

        # Process when we have a full block (4 words = 16 bytes for AES)
        if len(self.input_fifo) >= 4:
            self._process_block()

    def _process_block(self):
        """Process a block through the crypto engine."""
        if len(self.input_fifo) < 4:
            return

        # Extract 16-byte block
        block = struct.pack('>IIII',
            self.input_fifo[0], self.input_fifo[1],
            self.input_fifo[2], self.input_fifo[3]
        )
        self.input_fifo = self.input_fifo[4:]

        # Process with OpenSSL
        if self._cipher:
            try:
                result = self._cipher.update(block)
                # Store result in output FIFO
                words = struct.unpack('>IIII', result)
                self.output_fifo.extend(words)
                self.log.debug(f"Processed block: {block.hex()} -> {result.hex()}")
            except Exception as e:
                self.log.error(f"Crypto error: {e}")
                # Return zeros on error
                self.output_fifo.extend([0, 0, 0, 0])
        else:
            # Fallback: return input as output (no crypto)
            self.output_fifo.extend(struct.unpack('>IIII', block))

    def _read_output(self) -> int:
        """Read from output FIFO."""
        if self.output_fifo:
            return self.output_fifo.pop(0)
        return 0

    def _get_status(self) -> int:
        """Get status register value."""
        sr = 0
        if len(self.input_fifo) == 0:
            sr |= self.SR_IFEM
        if len(self.input_fifo) < 8:
            sr |= self.SR_IFNF
        if len(self.output_fifo) > 0:
            sr |= self.SR_OFNE
        if len(self.output_fifo) >= 8:
            sr |= self.SR_OFFU
        return sr


class STM32HashEngine:
    """
    STM32F4 HASH peripheral bridge to OpenSSL.

    Supports MD5, SHA-1, SHA-224, SHA-256.

    Register Map (0x50060400):
        CR      0x00    Control register
        DIN     0x04    Data input
        STR     0x08    Start register
        HR0-4   0x0C-1C Hash result registers
        IMR     0x20    Interrupt mask
        SR      0x24    Status register
        CSR0-53 0xF8+   Context swap registers
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

    # CR bits
    CR_INIT = (1 << 2)      # Initialize
    CR_DMAE = (1 << 3)      # DMA enable
    CR_DATATYPE = (3 << 4)  # Data type
    CR_MODE = (1 << 6)      # 0=hash, 1=HMAC
    CR_ALGO0 = (1 << 7)     # Algorithm bit 0
    CR_NBW = (0xF << 8)     # Number of valid bytes in last word
    CR_DINNE = (1 << 12)    # DIN not empty
    CR_MDMAT = (1 << 13)    # Multiple DMA transfers
    CR_LKEY = (1 << 16)     # Long key
    CR_ALGO1 = (1 << 18)    # Algorithm bit 1

    # SR bits
    SR_DINIS = (1 << 0)     # Data input interrupt status
    SR_DCIS = (1 << 1)      # Digest calculation complete
    SR_DMAS = (1 << 2)      # DMA status
    SR_BUSY = (1 << 3)      # Busy

    def __init__(self, base: int = 0x50060400):
        self.base = base
        self.size = 0x400
        self.log = logging.getLogger('HASH')

        self.cr = 0
        self.sr = 0
        self.imr = 0

        # Hash result registers
        self.hr = [0] * 8  # HR0-HR7 for SHA-256

        # Data buffer
        self.data_buffer = bytearray()

        # OpenSSL hash context
        self._hasher = None
        self._openssl_available = self._check_openssl()

    def _check_openssl(self) -> bool:
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.backends import default_backend
            return True
        except ImportError:
            return False

    def read(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.SR:
            return self.sr
        elif self.HR0 <= offset <= self.HR4 + 12:
            idx = (offset - self.HR0) // 4
            if idx < len(self.hr):
                return self.hr[idx]
        elif offset == self.IMR:
            return self.imr
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self._write_cr(value)
        elif offset == self.DIN:
            self._write_data(value)
        elif offset == self.STR:
            self._start_digest(value)
        elif offset == self.IMR:
            self.imr = value

    def _write_cr(self, value: int):
        old_cr = self.cr
        self.cr = value

        # Initialize
        if value & self.CR_INIT:
            self._init_hash()
            self.cr &= ~self.CR_INIT

    def _init_hash(self):
        """Initialize hash context based on algorithm selection."""
        if not self._openssl_available:
            return

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.backends import default_backend

        # Get algorithm from CR
        algo = ((self.cr >> 7) & 1) | (((self.cr >> 18) & 1) << 1)

        algo_map = {
            0b00: hashes.SHA1(),
            0b01: hashes.MD5(),
            0b10: hashes.SHA256(),
            0b11: hashes.SHA256(),  # SHA-224 approximation
        }

        hash_algo = algo_map.get(algo, hashes.SHA256())
        self._hasher = hashes.Hash(hash_algo, backend=default_backend())
        self.data_buffer.clear()
        self.log.info(f"Hash initialized: algo={algo}")

    def _write_data(self, value: int):
        """Write data to hash engine."""
        # Add 4 bytes to buffer
        self.data_buffer.extend(struct.pack('>I', value))

        # Update hash
        if self._hasher and len(self.data_buffer) >= 64:
            self._hasher.update(bytes(self.data_buffer[:64]))
            self.data_buffer = self.data_buffer[64:]

    def _start_digest(self, value: int):
        """Start digest calculation."""
        nbw = (value >> 8) & 0x1F  # Number of valid bits in last word

        # Process remaining data
        if self._hasher:
            if self.data_buffer:
                # Truncate to valid bytes
                valid_bytes = (len(self.data_buffer) * 8 + nbw) // 8
                self._hasher.update(bytes(self.data_buffer[:valid_bytes]))

            # Finalize
            try:
                digest = self._hasher.finalize()

                # Store in HR registers
                for i in range(min(len(digest) // 4, 8)):
                    self.hr[i] = struct.unpack('>I', digest[i*4:(i+1)*4])[0]

                self.log.info(f"Hash complete: {digest.hex()}")
                self.sr |= self.SR_DCIS  # Digest complete

            except Exception as e:
                self.log.error(f"Hash error: {e}")


# =============================================================================
# CAN BRIDGE -> SOCKETCAN / SCAPY
# =============================================================================

@dataclass
class CANMessage:
    """CAN message structure."""
    arbitration_id: int
    data: bytes
    is_extended: bool = False
    is_remote: bool = False
    is_error: bool = False
    timestamp: float = 0.0


class CANBridgeBackend(ABC):
    """Abstract CAN backend."""

    @abstractmethod
    async def connect(self) -> bool:
        pass

    @abstractmethod
    async def disconnect(self):
        pass

    @abstractmethod
    async def send(self, msg: CANMessage) -> bool:
        pass

    @abstractmethod
    async def receive(self, timeout: float = 1.0) -> Optional[CANMessage]:
        pass


class SocketCANBackend(CANBridgeBackend):
    """
    SocketCAN backend for Linux.

    Uses native Linux CAN socket interface.
    Requires: can-utils, configured CAN interface (vcan0, can0, etc.)

    Setup:
        sudo modprobe vcan
        sudo ip link add dev vcan0 type vcan
        sudo ip link set up vcan0
    """

    def __init__(self, interface: str = "vcan0"):
        self.interface = interface
        self.socket = None
        self.log = logging.getLogger(f'CAN.{interface}')

    async def connect(self) -> bool:
        """Connect to CAN interface."""
        try:
            import socket as sock

            # Create CAN socket
            self.socket = sock.socket(sock.AF_CAN, sock.SOCK_RAW, sock.CAN_RAW)
            self.socket.setblocking(False)
            self.socket.bind((self.interface,))
            self.log.info(f"Connected to {self.interface}")
            return True

        except Exception as e:
            self.log.error(f"Failed to connect: {e}")
            return False

    async def disconnect(self):
        """Disconnect from CAN interface."""
        if self.socket:
            self.socket.close()
            self.socket = None

    async def send(self, msg: CANMessage) -> bool:
        """Send CAN message."""
        if not self.socket:
            return False

        try:
            # Build CAN frame
            can_id = msg.arbitration_id
            if msg.is_extended:
                can_id |= 0x80000000  # EFF flag
            if msg.is_remote:
                can_id |= 0x40000000  # RTR flag
            if msg.is_error:
                can_id |= 0x20000000  # ERR flag

            # CAN frame: can_id (4) + dlc (1) + pad (3) + data (8)
            dlc = len(msg.data)
            data_padded = msg.data.ljust(8, b'\x00')
            frame = struct.pack('=IB3x8s', can_id, dlc, data_padded)

            loop = asyncio.get_event_loop()
            await loop.sock_sendall(self.socket, frame)
            self.log.debug(f"TX: ID=0x{msg.arbitration_id:X} Data={msg.data.hex()}")
            return True

        except Exception as e:
            self.log.error(f"Send error: {e}")
            return False

    async def receive(self, timeout: float = 1.0) -> Optional[CANMessage]:
        """Receive CAN message."""
        if not self.socket:
            return None

        try:
            loop = asyncio.get_event_loop()

            # Wait for data with timeout
            try:
                frame = await asyncio.wait_for(
                    loop.sock_recv(self.socket, 16),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                return None

            if len(frame) < 16:
                return None

            # Parse CAN frame
            can_id, dlc = struct.unpack('=IB', frame[:5])
            data = frame[8:8+dlc]

            msg = CANMessage(
                arbitration_id=can_id & 0x1FFFFFFF,
                data=data,
                is_extended=bool(can_id & 0x80000000),
                is_remote=bool(can_id & 0x40000000),
                is_error=bool(can_id & 0x20000000)
            )

            self.log.debug(f"RX: ID=0x{msg.arbitration_id:X} Data={msg.data.hex()}")
            return msg

        except Exception as e:
            self.log.error(f"Receive error: {e}")
            return None


class ScapyCANBackend(CANBridgeBackend):
    """
    Scapy-based CAN backend.

    Uses Scapy for CAN communication, supporting various interfaces.
    Requires: scapy with CAN support
    """

    def __init__(self, interface: str = "vcan0"):
        self.interface = interface
        self.socket = None
        self.log = logging.getLogger(f'CAN.Scapy.{interface}')

    async def connect(self) -> bool:
        """Connect using Scapy."""
        try:
            from scapy.contrib.cansocket import CANSocket
            from scapy.config import conf

            # Use native socket for better async support
            loop = asyncio.get_event_loop()
            executor = get_bridge_executor()

            def _connect():
                return CANSocket(iface=self.interface)

            self.socket = await loop.run_in_executor(executor, _connect)
            self.log.info(f"Scapy CAN connected to {self.interface}")
            return True

        except Exception as e:
            self.log.error(f"Scapy CAN connect failed: {e}")
            return False

    async def disconnect(self):
        if self.socket:
            self.socket.close()
            self.socket = None

    async def send(self, msg: CANMessage) -> bool:
        """Send CAN message via Scapy."""
        if not self.socket:
            return False

        try:
            from scapy.layers.can import CAN

            loop = asyncio.get_event_loop()
            executor = get_bridge_executor()

            pkt = CAN(identifier=msg.arbitration_id, data=msg.data)

            def _send():
                self.socket.send(pkt)

            await loop.run_in_executor(executor, _send)
            return True

        except Exception as e:
            self.log.error(f"Scapy send error: {e}")
            return False

    async def receive(self, timeout: float = 1.0) -> Optional[CANMessage]:
        """Receive CAN message via Scapy."""
        if not self.socket:
            return None

        try:
            loop = asyncio.get_event_loop()
            executor = get_bridge_executor()

            def _recv():
                pkt = self.socket.recv(timeout=timeout)
                return pkt

            pkt = await loop.run_in_executor(executor, _recv)

            if pkt:
                from scapy.layers.can import CAN
                if CAN in pkt:
                    return CANMessage(
                        arbitration_id=pkt[CAN].identifier,
                        data=bytes(pkt[CAN].data)
                    )
            return None

        except Exception as e:
            self.log.error(f"Scapy receive error: {e}")
            return None


class STM32CANController:
    """
    STM32 bxCAN controller bridge.

    Maps STM32 CAN peripheral registers to SocketCAN/Scapy backend.

    Register Map (CAN1: 0x40006400, CAN2: 0x40006800):
        MCR     0x00    Master control
        MSR     0x04    Master status
        TSR     0x08    Transmit status
        RF0R    0x0C    Receive FIFO 0
        RF1R    0x10    Receive FIFO 1
        IER     0x14    Interrupt enable
        ESR     0x18    Error status
        BTR     0x1C    Bit timing
        TI0R    0x180   TX mailbox 0 identifier
        TDT0R   0x184   TX mailbox 0 data length/timestamp
        TDL0R   0x188   TX mailbox 0 data low
        TDH0R   0x18C   TX mailbox 0 data high
        RI0R    0x1B0   RX FIFO 0 mailbox identifier
        RDT0R   0x1B4   RX FIFO 0 data length/timestamp
        RDL0R   0x1B8   RX FIFO 0 data low
        RDH0R   0x1BC   RX FIFO 0 data high
    """

    # Register offsets
    MCR = 0x00
    MSR = 0x04
    TSR = 0x08
    RF0R = 0x0C
    RF1R = 0x10
    IER = 0x14
    ESR = 0x18
    BTR = 0x1C

    # TX Mailboxes (3 total)
    TI0R = 0x180
    TDT0R = 0x184
    TDL0R = 0x188
    TDH0R = 0x18C

    # RX FIFO 0
    RI0R = 0x1B0
    RDT0R = 0x1B4
    RDL0R = 0x1B8
    RDH0R = 0x1BC

    # MCR bits
    MCR_INRQ = (1 << 0)   # Initialization request
    MCR_SLEEP = (1 << 1)  # Sleep mode
    MCR_TXFP = (1 << 2)   # TX FIFO priority
    MCR_RFLM = (1 << 3)   # Receive FIFO locked
    MCR_NART = (1 << 4)   # No auto retransmit
    MCR_AWUM = (1 << 5)   # Auto wakeup
    MCR_ABOM = (1 << 6)   # Auto bus-off management

    # MSR bits
    MSR_INAK = (1 << 0)   # Initialization acknowledge
    MSR_SLAK = (1 << 1)   # Sleep acknowledge

    # TSR bits
    TSR_RQCP0 = (1 << 0)  # Request completed mailbox 0
    TSR_TXOK0 = (1 << 1)  # TX OK mailbox 0
    TSR_TME0 = (1 << 26)  # TX mailbox 0 empty
    TSR_TME1 = (1 << 27)  # TX mailbox 1 empty
    TSR_TME2 = (1 << 28)  # TX mailbox 2 empty

    def __init__(self, name: str = "CAN1", base: int = 0x40006400,
                 backend: Optional[CANBridgeBackend] = None):
        self.name = name
        self.base = base
        self.size = 0x400
        self.log = logging.getLogger(f'CAN.{name}')

        # Backend
        self.backend = backend

        # Registers
        self.mcr = self.MCR_SLEEP  # Start in sleep mode
        self.msr = self.MSR_SLAK
        self.tsr = self.TSR_TME0 | self.TSR_TME1 | self.TSR_TME2  # All empty
        self.rf0r = 0
        self.rf1r = 0
        self.ier = 0
        self.esr = 0
        self.btr = 0

        # TX Mailboxes
        self.tx_mailboxes = [{'tir': 0, 'tdtr': 0, 'tdlr': 0, 'tdhr': 0} for _ in range(3)]

        # RX FIFOs
        self.rx_fifo0: List[CANMessage] = []
        self.rx_fifo1: List[CANMessage] = []

        # Background receive task
        self._rx_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        """Connect to CAN backend and start receive task."""
        if self.backend:
            if await self.backend.connect():
                self._rx_task = asyncio.create_task(self._rx_loop())
                return True
        return False

    async def disconnect(self):
        """Disconnect from CAN backend."""
        if self._rx_task:
            self._rx_task.cancel()
            try:
                await self._rx_task
            except asyncio.CancelledError:
                pass
        if self.backend:
            await self.backend.disconnect()

    async def _rx_loop(self):
        """Background receive loop."""
        while True:
            try:
                msg = await self.backend.receive(timeout=0.1)
                if msg:
                    # Add to FIFO 0 (simplified - real HW has filters)
                    if len(self.rx_fifo0) < 3:
                        self.rx_fifo0.append(msg)
                        self.rf0r = (self.rf0r & ~0x3) | len(self.rx_fifo0)
                        self.log.debug(f"RX FIFO0: ID=0x{msg.arbitration_id:X}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error(f"RX error: {e}")
                await asyncio.sleep(0.1)

    def read(self, offset: int, size: int) -> int:
        if offset == self.MCR:
            return self.mcr
        elif offset == self.MSR:
            return self.msr
        elif offset == self.TSR:
            return self.tsr
        elif offset == self.RF0R:
            return self.rf0r
        elif offset == self.RF1R:
            return self.rf1r
        elif offset == self.IER:
            return self.ier
        elif offset == self.ESR:
            return self.esr
        elif offset == self.BTR:
            return self.btr
        # RX FIFO 0 mailbox
        elif offset == self.RI0R:
            if self.rx_fifo0:
                msg = self.rx_fifo0[0]
                return (msg.arbitration_id << 21) | (1 if msg.is_extended else 0)
        elif offset == self.RDT0R:
            if self.rx_fifo0:
                return len(self.rx_fifo0[0].data)
        elif offset == self.RDL0R:
            if self.rx_fifo0:
                data = self.rx_fifo0[0].data.ljust(4, b'\x00')
                return struct.unpack('<I', data[:4])[0]
        elif offset == self.RDH0R:
            if self.rx_fifo0:
                data = self.rx_fifo0[0].data.ljust(8, b'\x00')
                return struct.unpack('<I', data[4:8])[0]
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == self.MCR:
            self._write_mcr(value)
        elif offset == self.TSR:
            self.tsr &= ~(value & 0x0F0F0F)  # Clear bits by writing 1
        elif offset == self.RF0R:
            if value & (1 << 5):  # RFOM0 - Release FIFO 0
                if self.rx_fifo0:
                    self.rx_fifo0.pop(0)
                    self.rf0r = (self.rf0r & ~0x3) | len(self.rx_fifo0)
        elif offset == self.IER:
            self.ier = value
        elif offset == self.BTR:
            self.btr = value
        # TX Mailbox 0
        elif offset == self.TI0R:
            self.tx_mailboxes[0]['tir'] = value
            if value & 1:  # TXRQ - transmit request
                asyncio.create_task(self._transmit_mailbox(0))
        elif offset == self.TDT0R:
            self.tx_mailboxes[0]['tdtr'] = value
        elif offset == self.TDL0R:
            self.tx_mailboxes[0]['tdlr'] = value
        elif offset == self.TDH0R:
            self.tx_mailboxes[0]['tdhr'] = value

    def _write_mcr(self, value: int):
        self.mcr = value

        if value & self.MCR_INRQ:
            # Enter initialization mode
            self.msr |= self.MSR_INAK
            self.msr &= ~self.MSR_SLAK
        else:
            # Exit initialization mode
            self.msr &= ~self.MSR_INAK

        if value & self.MCR_SLEEP:
            self.msr |= self.MSR_SLAK
        else:
            self.msr &= ~self.MSR_SLAK

    async def _transmit_mailbox(self, mailbox: int):
        """Transmit message from mailbox."""
        if not self.backend:
            return

        mb = self.tx_mailboxes[mailbox]
        tir = mb['tir']
        tdtr = mb['tdtr']
        tdlr = mb['tdlr']
        tdhr = mb['tdhr']

        # Parse mailbox registers
        is_extended = bool(tir & (1 << 2))
        if is_extended:
            arb_id = (tir >> 3) & 0x1FFFFFFF
        else:
            arb_id = (tir >> 21) & 0x7FF

        dlc = tdtr & 0xF
        data = struct.pack('<II', tdlr, tdhr)[:dlc]

        msg = CANMessage(
            arbitration_id=arb_id,
            data=data,
            is_extended=is_extended
        )

        success = await self.backend.send(msg)

        # Update TSR
        if success:
            self.tsr |= (self.TSR_RQCP0 | self.TSR_TXOK0) << (mailbox * 8)
            self.tsr |= (self.TSR_TME0 << mailbox)
            self.log.debug(f"TX complete: ID=0x{arb_id:X}")


# =============================================================================
# BLUETOOTH BRIDGE -> HCI / BLUEZ
# =============================================================================

class BluetoothBridgeBackend(ABC):
    """Abstract Bluetooth backend."""

    @abstractmethod
    async def connect(self) -> bool:
        pass

    @abstractmethod
    async def disconnect(self):
        pass

    @abstractmethod
    async def send_hci(self, packet: bytes) -> bool:
        pass

    @abstractmethod
    async def receive_hci(self, timeout: float = 1.0) -> Optional[bytes]:
        pass


class HCISocketBackend(BluetoothBridgeBackend):
    """
    Linux HCI socket backend.

    Connects to Bluetooth adapter via HCI socket interface.
    Requires: BlueZ, appropriate permissions (root or CAP_NET_RAW)

    Usage:
        backend = HCISocketBackend(hci_dev=0)  # hci0
        await backend.connect()
    """

    # HCI packet types
    HCI_COMMAND = 0x01
    HCI_ACL_DATA = 0x02
    HCI_SCO_DATA = 0x03
    HCI_EVENT = 0x04

    def __init__(self, hci_dev: int = 0):
        self.hci_dev = hci_dev
        self.socket = None
        self.log = logging.getLogger(f'BT.hci{hci_dev}')

    async def connect(self) -> bool:
        """Connect to HCI device."""
        try:
            import socket as sock

            # HCI constants
            AF_BLUETOOTH = 31
            BTPROTO_HCI = 1
            HCI_CHANNEL_RAW = 0
            HCI_CHANNEL_USER = 1

            # Create HCI socket
            self.socket = sock.socket(AF_BLUETOOTH, sock.SOCK_RAW, BTPROTO_HCI)

            # Bind to device
            # struct sockaddr_hci { sa_family_t hci_family; unsigned short hci_dev; unsigned short hci_channel; }
            self.socket.bind((self.hci_dev, HCI_CHANNEL_RAW))
            self.socket.setblocking(False)

            self.log.info(f"Connected to hci{self.hci_dev}")
            return True

        except Exception as e:
            self.log.error(f"HCI connect failed: {e}")
            return False

    async def disconnect(self):
        if self.socket:
            self.socket.close()
            self.socket = None

    async def send_hci(self, packet: bytes) -> bool:
        """Send HCI packet."""
        if not self.socket:
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.sock_sendall(self.socket, packet)
            self.log.debug(f"TX: {packet.hex()}")
            return True
        except Exception as e:
            self.log.error(f"HCI send error: {e}")
            return False

    async def receive_hci(self, timeout: float = 1.0) -> Optional[bytes]:
        """Receive HCI packet."""
        if not self.socket:
            return None

        try:
            loop = asyncio.get_event_loop()
            data = await asyncio.wait_for(
                loop.sock_recv(self.socket, 260),  # Max HCI packet size
                timeout=timeout
            )
            self.log.debug(f"RX: {data.hex()}")
            return data
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            self.log.error(f"HCI receive error: {e}")
            return None


class BlueZDBusBackend(BluetoothBridgeBackend):
    """
    BlueZ D-Bus backend.

    Uses BlueZ D-Bus API for Bluetooth operations.
    Requires: BlueZ, python-dbus or dbus-next
    """

    def __init__(self, adapter: str = "hci0"):
        self.adapter = adapter
        self.bus = None
        self.adapter_path = f"/org/bluez/{adapter}"
        self.log = logging.getLogger(f'BT.DBus.{adapter}')

    async def connect(self) -> bool:
        """Connect to BlueZ via D-Bus."""
        try:
            from dbus_next.aio import MessageBus
            from dbus_next import BusType

            self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

            # Get adapter interface
            introspection = await self.bus.introspect('org.bluez', self.adapter_path)
            proxy = self.bus.get_proxy_object('org.bluez', self.adapter_path, introspection)

            self.adapter_iface = proxy.get_interface('org.bluez.Adapter1')
            self.log.info(f"Connected to BlueZ adapter {self.adapter}")
            return True

        except Exception as e:
            self.log.error(f"BlueZ D-Bus connect failed: {e}")
            return False

    async def disconnect(self):
        if self.bus:
            self.bus.disconnect()
            self.bus = None

    async def send_hci(self, packet: bytes) -> bool:
        """Send HCI command via BlueZ (limited support)."""
        # D-Bus API doesn't directly expose raw HCI
        # This is a placeholder - use HCISocketBackend for raw access
        self.log.warning("Raw HCI not supported via D-Bus")
        return False

    async def receive_hci(self, timeout: float = 1.0) -> Optional[bytes]:
        self.log.warning("Raw HCI not supported via D-Bus")
        return None

    async def start_discovery(self):
        """Start Bluetooth discovery."""
        if self.adapter_iface:
            await self.adapter_iface.call_start_discovery()

    async def stop_discovery(self):
        """Stop Bluetooth discovery."""
        if self.adapter_iface:
            await self.adapter_iface.call_stop_discovery()


class NordicBLEController:
    """
    Nordic nRF52 BLE controller bridge.

    Maps Nordic RADIO peripheral to HCI backend for real BLE communication.

    This provides a high-level bridge - the RADIO peripheral handles
    BLE link layer while this bridges to host HCI.
    """

    def __init__(self, backend: Optional[BluetoothBridgeBackend] = None):
        self.backend = backend
        self.log = logging.getLogger('BLE.Nordic')

        # BLE state
        self.advertising = False
        self.scanning = False
        self.connected = False

        # HCI state
        self._rx_task: Optional[asyncio.Task] = None
        self._event_queue: asyncio.Queue = asyncio.Queue()

    async def connect(self) -> bool:
        """Connect to BLE backend."""
        if self.backend:
            if await self.backend.connect():
                self._rx_task = asyncio.create_task(self._hci_rx_loop())
                return True
        return False

    async def disconnect(self):
        if self._rx_task:
            self._rx_task.cancel()
        if self.backend:
            await self.backend.disconnect()

    async def _hci_rx_loop(self):
        """Receive HCI events from backend."""
        while True:
            try:
                packet = await self.backend.receive_hci(timeout=0.1)
                if packet:
                    await self._process_hci_event(packet)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error(f"HCI RX error: {e}")

    async def _process_hci_event(self, packet: bytes):
        """Process incoming HCI event."""
        if len(packet) < 2:
            return

        pkt_type = packet[0]

        if pkt_type == HCISocketBackend.HCI_EVENT:
            event_code = packet[1]
            self.log.debug(f"HCI Event: 0x{event_code:02X}")
            await self._event_queue.put(packet)

    async def send_hci_command(self, opcode: int, params: bytes = b'') -> bool:
        """Send HCI command."""
        if not self.backend:
            return False

        # Build HCI command packet
        packet = bytes([HCISocketBackend.HCI_COMMAND])
        packet += struct.pack('<H', opcode)
        packet += bytes([len(params)])
        packet += params

        return await self.backend.send_hci(packet)

    async def reset(self) -> bool:
        """Send HCI Reset command."""
        return await self.send_hci_command(0x0C03)  # HCI_Reset

    async def set_advertising_data(self, data: bytes) -> bool:
        """Set BLE advertising data."""
        # HCI_LE_Set_Advertising_Data
        padded = data.ljust(31, b'\x00')
        params = bytes([len(data)]) + padded
        return await self.send_hci_command(0x2008, params)

    async def start_advertising(self) -> bool:
        """Start BLE advertising."""
        # HCI_LE_Set_Advertise_Enable
        success = await self.send_hci_command(0x200A, bytes([0x01]))
        if success:
            self.advertising = True
        return success

    async def stop_advertising(self) -> bool:
        """Stop BLE advertising."""
        success = await self.send_hci_command(0x200A, bytes([0x00]))
        if success:
            self.advertising = False
        return success


# =============================================================================
# FACTORY AND UTILITIES
# =============================================================================

def create_crypto_bridge(soc_type: str = "stm32f4") -> Tuple[STM32CryptoEngine, STM32HashEngine]:
    """Create crypto bridges for SoC."""
    if "stm32" in soc_type.lower():
        return STM32CryptoEngine(), STM32HashEngine()
    raise ValueError(f"Unsupported SoC: {soc_type}")


def create_can_bridge(interface: str = "vcan0", backend: str = "socketcan") -> STM32CANController:
    """Create CAN bridge."""
    if backend == "socketcan":
        be = SocketCANBackend(interface)
    elif backend == "scapy":
        be = ScapyCANBackend(interface)
    else:
        raise ValueError(f"Unknown CAN backend: {backend}")

    return STM32CANController(backend=be)


def create_bluetooth_bridge(hci_dev: int = 0, backend: str = "hci") -> NordicBLEController:
    """Create Bluetooth bridge."""
    if backend == "hci":
        be = HCISocketBackend(hci_dev)
    elif backend == "dbus":
        be = BlueZDBusBackend(f"hci{hci_dev}")
    else:
        raise ValueError(f"Unknown BT backend: {backend}")

    return NordicBLEController(backend=be)


# =============================================================================
# DEMO
# =============================================================================

async def demo():
    """Demo peripheral bridges."""
    logging.basicConfig(level=logging.DEBUG, format='%(name)-12s: %(message)s')

    print("=" * 60)
    print("MCUemu Peripheral Bridges Demo")
    print("=" * 60)

    # Test crypto engine
    print("\n--- Crypto Engine (OpenSSL) ---")
    crypto = STM32CryptoEngine()

    # Set up AES-128-ECB encryption
    # Key: 0x00010203...0F
    for i in range(4):
        crypto.write(crypto.K0LR + i*4, 4, 0x00010203 + i*0x04040404)

    # Enable with AES-ECB, 128-bit key, encrypt
    crypto.write(crypto.CR, 4, (STM32CryptoAlgorithm.AES_ECB << 3) | crypto.CR_CRYPEN)

    # Write test data
    test_data = [0x00112233, 0x44556677, 0x8899AABB, 0xCCDDEEFF]
    for word in test_data:
        crypto.write(crypto.DIN, 4, word)

    # Read result
    print("Input:  ", ' '.join(f'{w:08X}' for w in test_data))
    result = [crypto.read(crypto.DOUT, 4) for _ in range(4)]
    print("Output: ", ' '.join(f'{w:08X}' for w in result))

    # Test CAN (requires vcan0 interface)
    print("\n--- CAN Bridge (SocketCAN) ---")
    try:
        can = create_can_bridge("vcan0", "socketcan")
        if await can.connect():
            # Send a test message
            can.tx_mailboxes[0]['tdlr'] = 0x12345678
            can.tx_mailboxes[0]['tdhr'] = 0x9ABCDEF0
            can.tx_mailboxes[0]['tdtr'] = 8  # DLC
            can.write(can.TI0R, 4, (0x123 << 21) | 1)  # ID + TXRQ

            await asyncio.sleep(0.1)
            await can.disconnect()
            print("CAN test complete")
        else:
            print("CAN not available (vcan0 not configured)")
    except Exception as e:
        print(f"CAN test skipped: {e}")

    # Test Bluetooth (requires HCI device)
    print("\n--- Bluetooth Bridge (HCI) ---")
    try:
        ble = create_bluetooth_bridge(0, "hci")
        if await ble.connect():
            await ble.reset()
            print("BLE HCI reset sent")
            await ble.disconnect()
        else:
            print("BLE not available (no HCI device or permission denied)")
    except Exception as e:
        print(f"BLE test skipped: {e}")

    print("\nDemo complete!")


if __name__ == '__main__':
    asyncio.run(demo())
