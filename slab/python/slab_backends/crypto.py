"""
SLAB Crypto Backend - Unified Cryptographic Operations

Uses Python cryptography library with fallback to hashlib/hmac.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import secrets
import hashlib
import hmac as hmac_module
from enum import Enum, auto
from typing import Optional, Union

# Try to import cryptography library
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO_LIB = True
except ImportError:
    HAS_CRYPTO_LIB = False

# Try to import for RSA/ECC
try:
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, padding as asym_padding
    from cryptography.hazmat.primitives import hashes, serialization
    HAS_ASYMMETRIC = True
except ImportError:
    HAS_ASYMMETRIC = False


class AESMode(Enum):
    """AES cipher modes."""
    ECB = auto()
    CBC = auto()
    CTR = auto()
    GCM = auto()
    CCM = auto()


class HashAlgorithm(Enum):
    """Hash algorithms."""
    MD5 = auto()
    SHA1 = auto()
    SHA224 = auto()
    SHA256 = auto()
    SHA384 = auto()
    SHA512 = auto()


class CryptoBackend:
    """
    Unified crypto backend for MCU peripheral emulation.

    Provides consistent interface regardless of underlying library.
    """

    def __init__(self):
        self._has_crypto = HAS_CRYPTO_LIB
        self._has_asymmetric = HAS_ASYMMETRIC

    @property
    def has_aes(self) -> bool:
        """Check if AES is available."""
        return self._has_crypto

    @property
    def has_rsa(self) -> bool:
        """Check if RSA is available."""
        return self._has_asymmetric

    @property
    def has_ecc(self) -> bool:
        """Check if ECC is available."""
        return self._has_asymmetric

    # ========== AES ==========

    def aes_encrypt(self, key: bytes, data: bytes,
                    mode: AESMode = AESMode.ECB,
                    iv: Optional[bytes] = None,
                    aad: Optional[bytes] = None) -> Union[bytes, tuple]:
        """
        AES encryption.

        Args:
            key: 16, 24, or 32 bytes
            data: Plaintext (must be block-aligned for ECB/CBC)
            mode: Cipher mode
            iv: Initialization vector (required for CBC/CTR/GCM/CCM)
            aad: Additional authenticated data (for GCM/CCM)

        Returns:
            Ciphertext, or (ciphertext, tag) for GCM/CCM
        """
        return aes_encrypt(key, data, mode, iv, aad)

    def aes_decrypt(self, key: bytes, data: bytes,
                    mode: AESMode = AESMode.ECB,
                    iv: Optional[bytes] = None,
                    tag: Optional[bytes] = None,
                    aad: Optional[bytes] = None) -> bytes:
        """
        AES decryption.

        Args:
            key: 16, 24, or 32 bytes
            data: Ciphertext
            mode: Cipher mode
            iv: Initialization vector
            tag: Authentication tag (for GCM/CCM)
            aad: Additional authenticated data (for GCM/CCM)

        Returns:
            Plaintext
        """
        return aes_decrypt(key, data, mode, iv, tag, aad)

    # ========== Hashing ==========

    def hash(self, data: bytes, algorithm: HashAlgorithm = HashAlgorithm.SHA256) -> bytes:
        """
        Calculate hash digest.

        Args:
            data: Data to hash
            algorithm: Hash algorithm

        Returns:
            Hash digest
        """
        return sha_hash(data, algorithm)

    def hmac(self, key: bytes, data: bytes,
             algorithm: HashAlgorithm = HashAlgorithm.SHA256) -> bytes:
        """
        Calculate HMAC.

        Args:
            key: HMAC key
            data: Data to authenticate
            algorithm: Hash algorithm

        Returns:
            HMAC digest
        """
        return hmac_digest(key, data, algorithm)

    # ========== RNG ==========

    def random_bytes(self, count: int) -> bytes:
        """Get cryptographically secure random bytes."""
        return get_random_bytes(count)

    def random_int(self, max_value: int) -> int:
        """Get random integer in range [0, max_value)."""
        return get_random_int(max_value)

    # ========== RSA ==========

    def rsa_generate_keypair(self, bits: int = 2048) -> tuple:
        """
        Generate RSA key pair.

        Args:
            bits: Key size (1024, 2048, 3072, 4096)

        Returns:
            (private_key, public_key) as PEM bytes
        """
        if not self._has_asymmetric:
            raise NotImplementedError("RSA requires cryptography library")

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=bits,
            backend=default_backend()
        )

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        return private_pem, public_pem

    # ========== ECC ==========

    def ecc_generate_keypair(self, curve: str = "P256") -> tuple:
        """
        Generate ECC key pair.

        Args:
            curve: Curve name (P256, P384, P521)

        Returns:
            (private_key, public_key) as PEM bytes
        """
        if not self._has_asymmetric:
            raise NotImplementedError("ECC requires cryptography library")

        curves = {
            "P256": ec.SECP256R1(),
            "P384": ec.SECP384R1(),
            "P521": ec.SECP521R1(),
        }

        if curve not in curves:
            raise ValueError(f"Unknown curve: {curve}")

        private_key = ec.generate_private_key(
            curves[curve],
            backend=default_backend()
        )

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        return private_pem, public_pem


# ========== Module-level functions ==========

def aes_encrypt(key: bytes, data: bytes,
                mode: AESMode = AESMode.ECB,
                iv: Optional[bytes] = None,
                aad: Optional[bytes] = None) -> Union[bytes, tuple]:
    """AES encryption (module function)."""
    if not HAS_CRYPTO_LIB:
        # Fallback: XOR with key (NOT SECURE - only for basic emulation)
        result = bytearray(len(data))
        for i, b in enumerate(data):
            result[i] = b ^ key[i % len(key)]
        return bytes(result)

    if mode == AESMode.ECB:
        cipher_mode = modes.ECB()
    elif mode == AESMode.CBC:
        cipher_mode = modes.CBC(iv or bytes(16))
    elif mode == AESMode.CTR:
        cipher_mode = modes.CTR(iv or bytes(16))
    elif mode == AESMode.GCM:
        cipher_mode = modes.GCM(iv or bytes(12))
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    cipher = Cipher(algorithms.AES(key), cipher_mode, backend=default_backend())
    encryptor = cipher.encryptor()

    if mode == AESMode.GCM and aad:
        encryptor.authenticate_additional_data(aad)

    ciphertext = encryptor.update(data) + encryptor.finalize()

    if mode == AESMode.GCM:
        return ciphertext, encryptor.tag

    return ciphertext


def aes_decrypt(key: bytes, data: bytes,
                mode: AESMode = AESMode.ECB,
                iv: Optional[bytes] = None,
                tag: Optional[bytes] = None,
                aad: Optional[bytes] = None) -> bytes:
    """AES decryption (module function)."""
    if not HAS_CRYPTO_LIB:
        # Fallback: XOR with key
        result = bytearray(len(data))
        for i, b in enumerate(data):
            result[i] = b ^ key[i % len(key)]
        return bytes(result)

    if mode == AESMode.ECB:
        cipher_mode = modes.ECB()
    elif mode == AESMode.CBC:
        cipher_mode = modes.CBC(iv or bytes(16))
    elif mode == AESMode.CTR:
        cipher_mode = modes.CTR(iv or bytes(16))
    elif mode == AESMode.GCM:
        cipher_mode = modes.GCM(iv or bytes(12), tag)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    cipher = Cipher(algorithms.AES(key), cipher_mode, backend=default_backend())
    decryptor = cipher.decryptor()

    if mode == AESMode.GCM and aad:
        decryptor.authenticate_additional_data(aad)

    return decryptor.update(data) + decryptor.finalize()


def sha_hash(data: bytes, algorithm: HashAlgorithm = HashAlgorithm.SHA256) -> bytes:
    """Calculate hash (module function)."""
    hash_funcs = {
        HashAlgorithm.MD5: hashlib.md5,
        HashAlgorithm.SHA1: hashlib.sha1,
        HashAlgorithm.SHA224: hashlib.sha224,
        HashAlgorithm.SHA256: hashlib.sha256,
        HashAlgorithm.SHA384: hashlib.sha384,
        HashAlgorithm.SHA512: hashlib.sha512,
    }

    func = hash_funcs.get(algorithm, hashlib.sha256)
    return func(data).digest()


def hmac_digest(key: bytes, data: bytes,
                algorithm: HashAlgorithm = HashAlgorithm.SHA256) -> bytes:
    """Calculate HMAC (module function)."""
    hash_names = {
        HashAlgorithm.MD5: 'md5',
        HashAlgorithm.SHA1: 'sha1',
        HashAlgorithm.SHA224: 'sha224',
        HashAlgorithm.SHA256: 'sha256',
        HashAlgorithm.SHA384: 'sha384',
        HashAlgorithm.SHA512: 'sha512',
    }

    name = hash_names.get(algorithm, 'sha256')
    return hmac_module.new(key, data, name).digest()


def get_random_bytes(count: int) -> bytes:
    """Get cryptographically secure random bytes."""
    return secrets.token_bytes(count)


def get_random_int(max_value: int) -> int:
    """Get random integer in range [0, max_value)."""
    if max_value <= 0:
        return 0
    return secrets.randbelow(max_value)


# Singleton instance
_backend = None

def get_crypto_backend() -> CryptoBackend:
    """Get the global crypto backend instance."""
    global _backend
    if _backend is None:
        _backend = CryptoBackend()
    return _backend
