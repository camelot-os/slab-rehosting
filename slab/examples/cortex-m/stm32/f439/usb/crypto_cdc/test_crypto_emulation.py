#!/usr/bin/env python3
"""
STM32F439 Crypto Emulation Test

Tests the CRYP and HASH peripherals by simulating firmware register access.
This validates the Python peripheral implementation matches what firmware would see.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os
import pytest

# Add the Python modules to path (6 levels up from examples/cortex-m/stm32/f439/usb/crypto_cdc/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', '..', 'python'))

from slab_stm32 import STM32F439PeripheralSet


@pytest.fixture
def stm32():
    """Create STM32F439 peripheral set for testing."""
    return STM32F439PeripheralSet()


def bytes_to_words(data: bytes, big_endian: bool = True) -> list:
    """Convert bytes to list of 32-bit words."""
    words = []
    for i in range(0, len(data), 4):
        chunk = data[i:i+4]
        if len(chunk) < 4:
            chunk = chunk + b'\x00' * (4 - len(chunk))
        if big_endian:
            words.append(int.from_bytes(chunk, 'big'))
        else:
            words.append(int.from_bytes(chunk, 'little'))
    return words


def words_to_bytes(words: list, big_endian: bool = True) -> bytes:
    """Convert list of 32-bit words to bytes."""
    result = b''
    for w in words:
        if big_endian:
            result += w.to_bytes(4, 'big')
        else:
            result += w.to_bytes(4, 'little')
    return result


def test_aes128_ecb_via_registers(stm32):
    """Test AES-128-ECB by writing to CRYP registers like firmware would."""
    print("\n=== Test: AES-128-ECB via Register Access ===")

    cryp = stm32.cryp

    # NIST test vector
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
    expected = bytes.fromhex("3ad77bb40d7a3660a89ecaf32466ef97")

    # 1. Disable and flush CRYP
    cryp.write(cryp.base + cryp.CR, 4, 0)
    cryp.write(cryp.base + cryp.CR, 4, cryp.CR_FFLUSH)

    # 2. Set key (128-bit key goes to K2LR, K2RR, K3LR, K3RR)
    key_words = bytes_to_words(key)
    cryp.write(cryp.base + cryp.K2LR, 4, key_words[0])
    cryp.write(cryp.base + cryp.K2RR, 4, key_words[1])
    cryp.write(cryp.base + cryp.K3LR, 4, key_words[2])
    cryp.write(cryp.base + cryp.K3RR, 4, key_words[3])

    # 3. Configure for AES-ECB encrypt, 128-bit key, 32-bit data type (no swap)
    cr_value = (cryp.ALGOMODE_AES_ECB << 3) | (0 << 8) | (0 << 6)  # ECB, 128-bit, no swap
    cryp.write(cryp.base + cryp.CR, 4, cr_value | cryp.CR_CRYPEN)

    # 4. Write plaintext (4 words = 16 bytes)
    pt_words = bytes_to_words(plaintext)
    for word in pt_words:
        cryp.write(cryp.base + cryp.DIN, 4, word)

    # 5. Read ciphertext
    ct_words = []
    for _ in range(4):
        val, _ = cryp.read(cryp.base + cryp.DOUT, 4)
        ct_words.append(val)

    result = words_to_bytes(ct_words)

    if result == expected:
        print(f"  PASS: Ciphertext matches")
        print(f"    Expected: {expected.hex()}")
        print(f"    Got:      {result.hex()}")
        return True
    else:
        print(f"  FAIL: Ciphertext mismatch")
        print(f"    Expected: {expected.hex()}")
        print(f"    Got:      {result.hex()}")
        return False


def test_sha256_via_registers(stm32):
    """Test SHA-256 by writing to HASH registers like firmware would."""
    print("\n=== Test: SHA-256 via Register Access ===")

    hash_periph = stm32.hash

    # Test vector: SHA-256("abc")
    data = b"abc"
    expected = bytes.fromhex(
        "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )

    # 1. Initialize HASH for SHA-256 (ALGO = 11, DATATYPE = 8-bit)
    cr_value = hash_periph.CR_ALGO0 | hash_periph.CR_ALGO1 | (2 << 4) | hash_periph.CR_INIT
    hash_periph.write(hash_periph.base + hash_periph.CR, 4, cr_value)

    # 2. Write data - for convenience, use the internal buffer directly
    #    In real firmware, data would be written word-by-word to DIN
    hash_periph.din_buf = bytearray(data)

    # 3. Trigger hash calculation (DCAL bit)
    remaining_bits = (len(data) % 4) * 8
    hash_periph.write(hash_periph.base + hash_periph.STR, 4,
                      hash_periph.STR_DCAL | remaining_bits)

    # 4. Read result from HR registers
    result = b''
    for offset in [hash_periph.HR0, hash_periph.HR1, hash_periph.HR2,
                   hash_periph.HR3, hash_periph.HR4, hash_periph.HR5,
                   hash_periph.HR6, hash_periph.HR7]:
        val, _ = hash_periph.read(hash_periph.base + offset, 4)
        result += val.to_bytes(4, 'big')

    if result == expected:
        print(f"  PASS: Hash matches")
        print(f"    Expected: {expected.hex()}")
        print(f"    Got:      {result.hex()}")
        return True
    else:
        print(f"  FAIL: Hash mismatch")
        print(f"    Expected: {expected.hex()}")
        print(f"    Got:      {result.hex()}")
        return False


def test_md5_via_registers(stm32):
    """Test MD5 by writing to HASH registers like firmware would."""
    print("\n=== Test: MD5 via Register Access ===")

    hash_periph = stm32.hash

    # Test vector: MD5("abc")
    data = b"abc"
    expected = bytes.fromhex("900150983cd24fb0d6963f7d28e17f72")

    # 1. Initialize HASH for MD5 (ALGO = 01, DATATYPE = 8-bit)
    cr_value = hash_periph.CR_ALGO0 | (2 << 4) | hash_periph.CR_INIT
    hash_periph.write(hash_periph.base + hash_periph.CR, 4, cr_value)

    # 2. Write data
    hash_periph.din_buf = bytearray(data)

    # 3. Trigger hash calculation
    remaining_bits = (len(data) % 4) * 8
    hash_periph.write(hash_periph.base + hash_periph.STR, 4,
                      hash_periph.STR_DCAL | remaining_bits)

    # 4. Read result (MD5 = 128 bits = 4 words)
    result = b''
    for offset in [hash_periph.HR0, hash_periph.HR1, hash_periph.HR2, hash_periph.HR3]:
        val, _ = hash_periph.read(hash_periph.base + offset, 4)
        result += val.to_bytes(4, 'big')

    if result == expected:
        print(f"  PASS: Hash matches")
        print(f"    Expected: {expected.hex()}")
        print(f"    Got:      {result.hex()}")
        return True
    else:
        print(f"  FAIL: Hash mismatch")
        print(f"    Expected: {expected.hex()}")
        print(f"    Got:      {result.hex()}")
        return False


def test_peripheral_addresses(stm32):
    """Verify peripherals are at correct addresses."""
    print("\n=== Test: Peripheral Address Mapping ===")

    passed = True

    # Check CRYP base
    if stm32.cryp.base == 0x50060000:
        print(f"  PASS: CRYP at 0x{stm32.cryp.base:08X}")
    else:
        print(f"  FAIL: CRYP at 0x{stm32.cryp.base:08X}, expected 0x50060000")
        passed = False

    # Check HASH base
    if stm32.hash.base == 0x50060400:
        print(f"  PASS: HASH at 0x{stm32.hash.base:08X}")
    else:
        print(f"  FAIL: HASH at 0x{stm32.hash.base:08X}, expected 0x50060400")
        passed = False

    # Check RNG base (should also be on AHB2)
    if stm32.rng.base == 0x50060800:
        print(f"  PASS: RNG at 0x{stm32.rng.base:08X}")
    else:
        print(f"  FAIL: RNG at 0x{stm32.rng.base:08X}, expected 0x50060800")
        passed = False

    return passed


def test_status_registers(stm32):
    """Test reading status registers."""
    print("\n=== Test: Status Register Access ===")

    passed = True

    # CRYP SR should show FIFO empty
    sr, _ = stm32.cryp.read(stm32.cryp.base + stm32.cryp.SR, 4)
    if sr & stm32.cryp.SR_IFEM:
        print(f"  PASS: CRYP SR shows input FIFO empty (0x{sr:08X})")
    else:
        print(f"  FAIL: CRYP SR = 0x{sr:08X}, expected IFEM bit set")
        passed = False

    # HASH SR should show ready for input
    sr, _ = stm32.hash.read(stm32.hash.base + stm32.hash.SR, 4)
    if sr & stm32.hash.SR_DINIS:
        print(f"  PASS: HASH SR shows ready for input (0x{sr:08X})")
    else:
        print(f"  FAIL: HASH SR = 0x{sr:08X}, expected DINIS bit set")
        passed = False

    return passed


def main():
    print("=" * 60)
    print("STM32F439 Crypto Peripheral Emulation Test")
    print("=" * 60)

    # Create STM32F439 peripheral set
    print("\nInitializing STM32F439 peripheral set...")
    stm32 = STM32F439PeripheralSet()
    print(f"  Device: {stm32.device}")
    print(f"  Family: {stm32.family}")
    print(f"  Peripherals: {len(stm32.peripherals)}")

    # Run tests
    results = []

    results.append(("Peripheral Addresses", test_peripheral_addresses(stm32)))
    results.append(("Status Registers", test_status_registers(stm32)))
    results.append(("AES-128-ECB", test_aes128_ecb_via_registers(stm32)))
    results.append(("SHA-256", test_sha256_via_registers(stm32)))
    results.append(("MD5", test_md5_via_registers(stm32)))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {passed} passed, {failed} failed")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
