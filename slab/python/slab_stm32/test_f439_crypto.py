"""
STM32F439 Crypto Peripheral Tests

Tests for CRYP (AES, DES, TDES) and HASH (MD5, SHA-1, SHA-224, SHA-256) peripherals.
Uses NIST test vectors for validation.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import pytest
import hashlib
import hmac

# Skip if PyCryptodome is not installed
pytest.importorskip("Crypto")

from .stm32_cryp import STM32F4CRYP
from .stm32_hash import STM32F4HASH


class TestSTM32F4CRYP:
    """Tests for STM32F4 CRYP peripheral."""

    def setup_method(self):
        """Create fresh CRYP instance for each test."""
        self.cryp = STM32F4CRYP()

    # =========================================================================
    # AES-128 ECB Tests (NIST FIPS 197 test vectors)
    # =========================================================================

    def test_aes128_ecb_encrypt(self):
        """Test AES-128 ECB encryption with NIST vector."""
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
        expected = bytes.fromhex("3ad77bb40d7a3660a89ecaf32466ef97")

        self.cryp.set_key(key, keysize=128)
        self.cryp.cr |= (self.cryp.ALGOMODE_AES_ECB << 3)

        result = self.cryp.encrypt_block(plaintext)
        assert result == expected, f"AES-128-ECB encrypt mismatch"

    def test_aes128_ecb_decrypt(self):
        """Test AES-128 ECB decryption with NIST vector."""
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        ciphertext = bytes.fromhex("3ad77bb40d7a3660a89ecaf32466ef97")
        expected = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")

        self.cryp.set_key(key, keysize=128)
        self.cryp.cr |= (self.cryp.ALGOMODE_AES_ECB << 3)

        result = self.cryp.decrypt_block(ciphertext)
        assert result == expected, f"AES-128-ECB decrypt mismatch"

    # =========================================================================
    # AES-256 ECB Tests
    # =========================================================================

    def test_aes256_ecb_encrypt(self):
        """Test AES-256 ECB encryption with NIST vector."""
        key = bytes.fromhex("603deb1015ca71be2b73aef0857d7781"
                           "1f352c073b6108d72d9810a30914dff4")
        plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
        expected = bytes.fromhex("f3eed1bdb5d2a03c064b5a7e3db181f8")

        self.cryp.set_key(key, keysize=256)
        self.cryp.cr |= (self.cryp.ALGOMODE_AES_ECB << 3)

        result = self.cryp.encrypt_block(plaintext)
        assert result == expected, f"AES-256-ECB encrypt mismatch"

    def test_aes256_ecb_decrypt(self):
        """Test AES-256 ECB decryption with NIST vector."""
        key = bytes.fromhex("603deb1015ca71be2b73aef0857d7781"
                           "1f352c073b6108d72d9810a30914dff4")
        ciphertext = bytes.fromhex("f3eed1bdb5d2a03c064b5a7e3db181f8")
        expected = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")

        self.cryp.set_key(key, keysize=256)
        self.cryp.cr |= (self.cryp.ALGOMODE_AES_ECB << 3)

        result = self.cryp.decrypt_block(ciphertext)
        assert result == expected, f"AES-256-ECB decrypt mismatch"

    # =========================================================================
    # AES-128 CBC Tests
    # =========================================================================

    def test_aes128_cbc_encrypt(self):
        """Test AES-128 CBC encryption with NIST vector."""
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
        expected = bytes.fromhex("7649abac8119b246cee98e9b12e9197d")

        self.cryp.set_key(key, keysize=128)
        self.cryp.set_iv(iv)
        self.cryp.cr |= (self.cryp.ALGOMODE_AES_CBC << 3)

        result = self.cryp.encrypt_block(plaintext)
        assert result == expected, f"AES-128-CBC encrypt mismatch"

    def test_aes128_cbc_decrypt(self):
        """Test AES-128 CBC decryption with NIST vector."""
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        ciphertext = bytes.fromhex("7649abac8119b246cee98e9b12e9197d")
        expected = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")

        self.cryp.set_key(key, keysize=128)
        self.cryp.set_iv(iv)
        self.cryp.cr |= (self.cryp.ALGOMODE_AES_CBC << 3)

        result = self.cryp.decrypt_block(ciphertext)
        assert result == expected, f"AES-128-CBC decrypt mismatch"

    # =========================================================================
    # Register Access Tests
    # =========================================================================

    def test_key_register_access(self):
        """Test key register read/write."""
        # Write to key registers
        self.cryp.write(self.cryp.base + self.cryp.K2LR, 4, 0xDEADBEEF)
        self.cryp.write(self.cryp.base + self.cryp.K2RR, 4, 0xCAFEBABE)

        # Read back
        val1, _ = self.cryp.read(self.cryp.base + self.cryp.K2LR, 4)
        val2, _ = self.cryp.read(self.cryp.base + self.cryp.K2RR, 4)

        assert val1 == 0xDEADBEEF
        assert val2 == 0xCAFEBABE

    def test_iv_register_access(self):
        """Test IV register read/write."""
        self.cryp.write(self.cryp.base + self.cryp.IV0LR, 4, 0x01020304)
        self.cryp.write(self.cryp.base + self.cryp.IV0RR, 4, 0x05060708)

        val1, _ = self.cryp.read(self.cryp.base + self.cryp.IV0LR, 4)
        val2, _ = self.cryp.read(self.cryp.base + self.cryp.IV0RR, 4)

        assert val1 == 0x01020304
        assert val2 == 0x05060708

    def test_status_register(self):
        """Test SR reflects FIFO state."""
        # Initially FIFO should be empty
        sr, _ = self.cryp.read(self.cryp.base + self.cryp.SR, 4)
        assert sr & self.cryp.SR_IFEM  # Input FIFO empty
        assert sr & self.cryp.SR_IFNF  # Input FIFO not full
        assert not (sr & self.cryp.SR_OFNE)  # Output FIFO empty

    def test_control_register_fflush(self):
        """Test FIFO flush via CR."""
        # Enable and write some data
        self.cryp.cr |= self.cryp.CR_CRYPEN | (self.cryp.ALGOMODE_AES_ECB << 3)
        self.cryp.write(self.cryp.base + self.cryp.DIN, 4, 0x12345678)

        # Flush
        self.cryp.write(self.cryp.base + self.cryp.CR, 4, self.cryp.CR_FFLUSH)

        # FIFO should be empty
        sr, _ = self.cryp.read(self.cryp.base + self.cryp.SR, 4)
        assert sr & self.cryp.SR_IFEM


class TestSTM32F4HASH:
    """Tests for STM32F4 HASH peripheral."""

    def setup_method(self):
        """Create fresh HASH instance for each test."""
        self.hash = STM32F4HASH()

    # =========================================================================
    # SHA-256 Tests
    # =========================================================================

    def test_sha256_empty(self):
        """Test SHA-256 of empty string."""
        expected = bytes.fromhex(
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855"
        )

        self.hash.set_algorithm('sha256')
        result = self.hash.hash_data(b'')

        assert result == expected, f"SHA-256 empty mismatch"

    def test_sha256_abc(self):
        """Test SHA-256 of 'abc'."""
        expected = bytes.fromhex(
            "ba7816bf8f01cfea414140de5dae2223"
            "b00361a396177a9cb410ff61f20015ad"
        )

        self.hash.set_algorithm('sha256')
        result = self.hash.hash_data(b'abc')

        assert result == expected, f"SHA-256 'abc' mismatch"

    def test_sha256_longer(self):
        """Test SHA-256 of longer message."""
        message = b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
        expected = bytes.fromhex(
            "248d6a61d20638b8e5c026930c3e6039"
            "a33ce45964ff2167f6ecedd419db06c1"
        )

        self.hash.set_algorithm('sha256')
        result = self.hash.hash_data(message)

        assert result == expected, f"SHA-256 longer message mismatch"

    # =========================================================================
    # MD5 Tests
    # =========================================================================

    def test_md5_empty(self):
        """Test MD5 of empty string."""
        expected = bytes.fromhex("d41d8cd98f00b204e9800998ecf8427e")

        self.hash.set_algorithm('md5')
        result = self.hash.hash_data(b'')

        assert result == expected, f"MD5 empty mismatch"

    def test_md5_abc(self):
        """Test MD5 of 'abc'."""
        expected = bytes.fromhex("900150983cd24fb0d6963f7d28e17f72")

        self.hash.set_algorithm('md5')
        result = self.hash.hash_data(b'abc')

        assert result == expected, f"MD5 'abc' mismatch"

    def test_md5_message(self):
        """Test MD5 of 'message digest'."""
        expected = bytes.fromhex("f96b697d7cb7938d525a2f31aaf161d0")

        self.hash.set_algorithm('md5')
        result = self.hash.hash_data(b'message digest')

        assert result == expected, f"MD5 'message digest' mismatch"

    # =========================================================================
    # SHA-1 Tests
    # =========================================================================

    def test_sha1_empty(self):
        """Test SHA-1 of empty string."""
        expected = bytes.fromhex("da39a3ee5e6b4b0d3255bfef95601890afd80709")

        self.hash.set_algorithm('sha1')
        result = self.hash.hash_data(b'')

        assert result == expected, f"SHA-1 empty mismatch"

    def test_sha1_abc(self):
        """Test SHA-1 of 'abc'."""
        expected = bytes.fromhex("a9993e364706816aba3e25717850c26c9cd0d89d")

        self.hash.set_algorithm('sha1')
        result = self.hash.hash_data(b'abc')

        assert result == expected, f"SHA-1 'abc' mismatch"

    # =========================================================================
    # SHA-224 Tests
    # =========================================================================

    def test_sha224_abc(self):
        """Test SHA-224 of 'abc'."""
        expected = bytes.fromhex(
            "23097d223405d8228642a477bda255b3"
            "2aadbce4bda0b3f7e36c9da7"
        )

        self.hash.set_algorithm('sha224')
        result = self.hash.hash_data(b'abc')

        assert result == expected, f"SHA-224 'abc' mismatch"

    # =========================================================================
    # HMAC Tests (RFC 4231)
    # =========================================================================

    def test_hmac_sha256_case1(self):
        """Test HMAC-SHA256 RFC 4231 Test Case 1."""
        key = bytes.fromhex("0b" * 20)
        data = b"Hi There"
        expected = bytes.fromhex(
            "b0344c61d8db38535ca8afceaf0bf12b"
            "881dc200c9833da726e9376c2e32cff7"
        )

        self.hash.set_algorithm('sha256')
        result = self.hash.hmac_data(key, data)

        assert result == expected, f"HMAC-SHA256 case 1 mismatch"

    def test_hmac_sha256_case2(self):
        """Test HMAC-SHA256 RFC 4231 Test Case 2."""
        key = b"Jefe"
        data = b"what do ya want for nothing?"
        expected = bytes.fromhex(
            "5bdcc146bf60754e6a042426089575c7"
            "5a003f089d2739839dec58b964ec3843"
        )

        self.hash.set_algorithm('sha256')
        result = self.hash.hmac_data(key, data)

        assert result == expected, f"HMAC-SHA256 case 2 mismatch"

    # =========================================================================
    # Register Access Tests
    # =========================================================================

    def test_cr_algorithm_bits(self):
        """Test CR algorithm bit encoding."""
        # SHA-1 (00)
        self.hash.set_algorithm('sha1')
        assert not (self.hash.cr & self.hash.CR_ALGO0)
        assert not (self.hash.cr & self.hash.CR_ALGO1)

        # MD5 (01)
        self.hash.set_algorithm('md5')
        assert self.hash.cr & self.hash.CR_ALGO0
        assert not (self.hash.cr & self.hash.CR_ALGO1)

        # SHA-224 (10)
        self.hash.set_algorithm('sha224')
        assert not (self.hash.cr & self.hash.CR_ALGO0)
        assert self.hash.cr & self.hash.CR_ALGO1

        # SHA-256 (11)
        self.hash.set_algorithm('sha256')
        assert self.hash.cr & self.hash.CR_ALGO0
        assert self.hash.cr & self.hash.CR_ALGO1

    def test_sr_dinis_bit(self):
        """Test SR DINIS (data input interrupt status)."""
        # Initially should be set (ready for input)
        sr, _ = self.hash.read(self.hash.base + self.hash.SR, 4)
        assert sr & self.hash.SR_DINIS

    def test_hash_result_registers(self):
        """Test reading hash result from HR registers."""
        self.hash.set_algorithm('sha256')
        self.hash.hash_data(b'test')

        # Read individual HR registers
        hr0, _ = self.hash.read(self.hash.base + self.hash.HR0, 4)
        hr1, _ = self.hash.read(self.hash.base + self.hash.HR1, 4)

        # Verify against Python hashlib
        expected = hashlib.sha256(b'test').digest()
        exp_hr0 = int.from_bytes(expected[0:4], 'big')
        exp_hr1 = int.from_bytes(expected[4:8], 'big')

        assert hr0 == exp_hr0
        assert hr1 == exp_hr1


class TestCryptoIntegration:
    """Integration tests combining CRYP and HASH."""

    def test_encrypt_then_hash(self):
        """Test encrypting data then hashing the ciphertext."""
        cryp = STM32F4CRYP()
        hash_periph = STM32F4HASH()

        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")

        # Encrypt
        cryp.set_key(key, keysize=128)
        cryp.cr |= (cryp.ALGOMODE_AES_ECB << 3)
        ciphertext = cryp.encrypt_block(plaintext)

        # Hash the ciphertext
        hash_periph.set_algorithm('sha256')
        digest = hash_periph.hash_data(ciphertext)

        # Verify against Python
        expected_ct = bytes.fromhex("3ad77bb40d7a3660a89ecaf32466ef97")
        expected_hash = hashlib.sha256(expected_ct).digest()

        assert ciphertext == expected_ct
        assert digest == expected_hash

    def test_roundtrip_aes128(self):
        """Test AES-128 encrypt then decrypt roundtrip."""
        cryp = STM32F4CRYP()

        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")

        # Encrypt
        cryp.set_key(key, keysize=128)
        cryp.cr |= (cryp.ALGOMODE_AES_ECB << 3)
        ciphertext = cryp.encrypt_block(plaintext)

        # Reset for decryption
        cryp.din_fifo.clear()
        cryp.dout_fifo.clear()

        # Decrypt
        decrypted = cryp.decrypt_block(ciphertext)

        assert decrypted == plaintext


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
