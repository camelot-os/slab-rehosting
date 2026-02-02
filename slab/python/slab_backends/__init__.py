"""
SLAB Backends - Hardware Abstraction and Protocol Bridges

Provides unified interfaces for:
- Crypto operations (AES, SHA, RSA, ECC, RNG)
- USB connectivity (USBIP server/client)
- CAN bus (SocketCAN)
- Display output (Qt/Pygame framebuffer)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.1.0"
__author__ = "Mathieu Renard"

from .crypto import (
    CryptoBackend,
    AESMode,
    HashAlgorithm,
    aes_encrypt,
    aes_decrypt,
    sha_hash,
    hmac_digest,
    get_random_bytes,
    get_random_int,
    get_crypto_backend,
)

from .usbip import (
    USBDevice,
    USBIPServer,
    USBDeviceDescriptor,
    USBConfigDescriptor,
    USBInterfaceDescriptor,
    USBEndpointDescriptor,
)

from .socketcan import (
    CANFrame,
    CANFDFrame,
    CANFlags,
    SocketCANInterface,
    CANBus,
    CANNode,
)

from .shm_mailbox import (
    SlabShmMailbox,
    ShmCommand,
    ShmFlags,
    RingEntry,
    SecurityContext,
)

__all__ = [
    "__version__",
    "__author__",
    # Crypto
    "CryptoBackend",
    "AESMode",
    "HashAlgorithm",
    "aes_encrypt",
    "aes_decrypt",
    "sha_hash",
    "hmac_digest",
    "get_random_bytes",
    "get_random_int",
    "get_crypto_backend",
    # USB
    "USBDevice",
    "USBIPServer",
    "USBDeviceDescriptor",
    "USBConfigDescriptor",
    "USBInterfaceDescriptor",
    "USBEndpointDescriptor",
    # CAN
    "CANFrame",
    "CANFDFrame",
    "CANFlags",
    "SocketCANInterface",
    "CANBus",
    "CANNode",
    # SHM Mailbox
    "SlabShmMailbox",
    "ShmCommand",
    "ShmFlags",
    "RingEntry",
    "SecurityContext",
]
