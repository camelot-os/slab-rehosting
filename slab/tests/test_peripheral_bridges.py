#!/usr/bin/env python3
"""
Test Suite for MCUemu Peripheral Bridges

Tests:
1. STM32 Crypto Engine -> OpenSSL (AES, DES, HASH)
2. CAN Bridge -> SocketCAN/Scapy
3. Bluetooth Bridge -> HCI

Author: Twisted Wires Security Lab
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import sys
import os
import unittest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add parent path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

from peripheral_bridges import (
    STM32CryptoEngine, STM32HashEngine, STM32CryptoAlgorithm,
    STM32CANController, CANMessage, SocketCANBackend, ScapyCANBackend,
    NordicBLEController, HCISocketBackend, BlueZDBusBackend,
    create_crypto_bridge, create_can_bridge, create_bluetooth_bridge
)


# =============================================================================
# CRYPTO ENGINE TESTS
# =============================================================================

class TestSTM32CryptoEngine(unittest.TestCase):
    """Test STM32 CRYP peripheral bridge to OpenSSL."""

    def setUp(self):
        self.crypto = STM32CryptoEngine()

    def test_register_init(self):
        """Test initial register values."""
        # CR should be 0
        self.assertEqual(self.crypto.read(self.crypto.CR, 4), 0)
        # SR should show input FIFO empty and not full
        sr = self.crypto.read(self.crypto.SR, 4)
        self.assertTrue(sr & self.crypto.SR_IFEM)  # Input empty
        self.assertTrue(sr & self.crypto.SR_IFNF)  # Input not full

    def test_key_register_write(self):
        """Test writing to key registers."""
        # Write 128-bit key
        test_key = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F]
        for i, word in enumerate(test_key):
            self.crypto.write(self.crypto.K0LR + i*4, 4, word)

        # Verify
        for i, expected in enumerate(test_key):
            self.assertEqual(self.crypto.key_regs[i], expected)

    def test_iv_register_write(self):
        """Test writing to IV registers."""
        test_iv = [0x10111213, 0x14151617, 0x18191A1B, 0x1C1D1E1F]
        for i, word in enumerate(test_iv):
            self.crypto.write(self.crypto.IV0LR + i*4, 4, word)

        # Verify
        for i, expected in enumerate(test_iv):
            self.assertEqual(self.crypto.iv_regs[i], expected)

    def test_aes_ecb_encrypt(self):
        """Test AES-128-ECB encryption."""
        # Skip if cryptography not available
        if not self.crypto._openssl_available:
            self.skipTest("cryptography library not available")

        # Set 128-bit key (all zeros for simplicity)
        for i in range(4):
            self.crypto.write(self.crypto.K0LR + i*4, 4, 0)

        # Enable: AES-ECB, 128-bit, encrypt
        cr = (STM32CryptoAlgorithm.AES_ECB << 3) | self.crypto.CR_CRYPEN
        self.crypto.write(self.crypto.CR, 4, cr)

        # Write plaintext block (16 bytes = 4 words)
        plaintext = [0x00112233, 0x44556677, 0x8899AABB, 0xCCDDEEFF]
        for word in plaintext:
            self.crypto.write(self.crypto.DIN, 4, word)

        # Read ciphertext
        ciphertext = [self.crypto.read(self.crypto.DOUT, 4) for _ in range(4)]

        # Verify output is different from input (encrypted)
        self.assertNotEqual(plaintext, ciphertext)

        # Verify we got 4 words
        self.assertEqual(len(ciphertext), 4)

    def test_aes_cbc_encrypt(self):
        """Test AES-128-CBC encryption."""
        if not self.crypto._openssl_available:
            self.skipTest("cryptography library not available")

        # Set key
        key = [0x2B7E1516, 0x28AED2A6, 0xABF71588, 0x09CF4F3C]
        for i, word in enumerate(key):
            self.crypto.write(self.crypto.K0LR + i*4, 4, word)

        # Set IV
        iv = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F]
        for i, word in enumerate(iv):
            self.crypto.write(self.crypto.IV0LR + i*4, 4, word)

        # Enable: AES-CBC, 128-bit, encrypt
        cr = (STM32CryptoAlgorithm.AES_CBC << 3) | self.crypto.CR_CRYPEN
        self.crypto.write(self.crypto.CR, 4, cr)

        # Write plaintext
        plaintext = [0x6BC1BEE2, 0x2E409F96, 0xE93D7E11, 0x7393172A]
        for word in plaintext:
            self.crypto.write(self.crypto.DIN, 4, word)

        # Read ciphertext
        ciphertext = [self.crypto.read(self.crypto.DOUT, 4) for _ in range(4)]

        self.assertNotEqual(plaintext, ciphertext)

    def test_fifo_status(self):
        """Test FIFO status flags."""
        # Initially empty
        sr = self.crypto.read(self.crypto.SR, 4)
        self.assertTrue(sr & self.crypto.SR_IFEM)
        self.assertFalse(sr & self.crypto.SR_OFNE)

        # Write some data (won't process without crypto enabled)
        self.crypto.input_fifo.append(0x12345678)

        sr = self.crypto.read(self.crypto.SR, 4)
        self.assertFalse(sr & self.crypto.SR_IFEM)  # Not empty now

    def test_fifo_flush(self):
        """Test FIFO flush via CR."""
        # Add data to FIFOs
        self.crypto.input_fifo = [1, 2, 3]
        self.crypto.output_fifo = [4, 5, 6]

        # Flush
        self.crypto.write(self.crypto.CR, 4, self.crypto.CR_FFLUSH)

        # Verify cleared
        self.assertEqual(len(self.crypto.input_fifo), 0)
        self.assertEqual(len(self.crypto.output_fifo), 0)


class TestSTM32HashEngine(unittest.TestCase):
    """Test STM32 HASH peripheral bridge to OpenSSL."""

    def setUp(self):
        self.hash = STM32HashEngine()

    def test_register_init(self):
        """Test initial register values."""
        self.assertEqual(self.hash.read(self.hash.CR, 4), 0)
        self.assertEqual(self.hash.read(self.hash.SR, 4), 0)

    def test_sha256_hash(self):
        """Test SHA-256 hash computation."""
        if not self.hash._openssl_available:
            self.skipTest("cryptography library not available")

        # Set SHA-256 algorithm (ALGO[1:0] = 10)
        cr = self.hash.CR_INIT | (1 << 18)  # ALGO1=1, ALGO0=0
        self.hash.write(self.hash.CR, 4, cr)

        # Write test data "abc"
        self.hash.write(self.hash.DIN, 4, 0x61626300)  # "abc\0" in big-endian

        # Start digest with 24 valid bits (3 bytes)
        self.hash.write(self.hash.STR, 4, (24 << 8))

        # Check digest complete flag
        sr = self.hash.read(self.hash.SR, 4)
        self.assertTrue(sr & self.hash.SR_DCIS)

        # Read hash result (first word)
        hr0 = self.hash.read(self.hash.HR0, 4)
        self.assertNotEqual(hr0, 0)

    def test_md5_hash(self):
        """Test MD5 hash computation."""
        if not self.hash._openssl_available:
            self.skipTest("cryptography library not available")

        # Set MD5 algorithm (ALGO = 01)
        cr = self.hash.CR_INIT | (1 << 7)  # ALGO0=1
        self.hash.write(self.hash.CR, 4, cr)

        # Write test data
        self.hash.write(self.hash.DIN, 4, 0x74657374)  # "test"

        # Start digest
        self.hash.write(self.hash.STR, 4, (32 << 8))

        # Verify completion
        sr = self.hash.read(self.hash.SR, 4)
        self.assertTrue(sr & self.hash.SR_DCIS)


# =============================================================================
# CAN BRIDGE TESTS
# =============================================================================

class TestCANMessage(unittest.TestCase):
    """Test CAN message structure."""

    def test_message_creation(self):
        """Test CAN message creation."""
        msg = CANMessage(
            arbitration_id=0x123,
            data=b'\x01\x02\x03\x04',
            is_extended=False
        )
        self.assertEqual(msg.arbitration_id, 0x123)
        self.assertEqual(msg.data, b'\x01\x02\x03\x04')
        self.assertFalse(msg.is_extended)

    def test_extended_message(self):
        """Test extended CAN message."""
        msg = CANMessage(
            arbitration_id=0x1ABCDEF,
            data=b'\xFF',
            is_extended=True
        )
        self.assertTrue(msg.is_extended)
        self.assertEqual(msg.arbitration_id, 0x1ABCDEF)


class TestSTM32CANController(unittest.TestCase):
    """Test STM32 CAN controller peripheral."""

    def setUp(self):
        self.can = STM32CANController(name="CAN1", base=0x40006400)

    def test_register_init(self):
        """Test initial register values."""
        # MCR starts in sleep mode
        mcr = self.can.read(self.can.MCR, 4)
        self.assertTrue(mcr & self.can.MCR_SLEEP)

        # MSR shows sleep acknowledge
        msr = self.can.read(self.can.MSR, 4)
        self.assertTrue(msr & self.can.MSR_SLAK)

        # TSR shows all TX mailboxes empty
        tsr = self.can.read(self.can.TSR, 4)
        self.assertTrue(tsr & self.can.TSR_TME0)
        self.assertTrue(tsr & self.can.TSR_TME1)
        self.assertTrue(tsr & self.can.TSR_TME2)

    def test_initialization_mode(self):
        """Test entering initialization mode."""
        # Request init mode
        self.can.write(self.can.MCR, 4, self.can.MCR_INRQ)

        # Check INAK is set
        msr = self.can.read(self.can.MSR, 4)
        self.assertTrue(msr & self.can.MSR_INAK)

        # Exit init mode
        self.can.write(self.can.MCR, 4, 0)
        msr = self.can.read(self.can.MSR, 4)
        self.assertFalse(msr & self.can.MSR_INAK)

    def test_tx_mailbox_write(self):
        """Test writing to TX mailbox."""
        # Write data
        self.can.write(self.can.TDL0R, 4, 0x12345678)
        self.can.write(self.can.TDH0R, 4, 0x9ABCDEF0)
        self.can.write(self.can.TDT0R, 4, 8)  # DLC=8

        # Verify stored
        self.assertEqual(self.can.tx_mailboxes[0]['tdlr'], 0x12345678)
        self.assertEqual(self.can.tx_mailboxes[0]['tdhr'], 0x9ABCDEF0)
        self.assertEqual(self.can.tx_mailboxes[0]['tdtr'], 8)

    def test_rx_fifo(self):
        """Test RX FIFO handling."""
        # Simulate received message
        msg = CANMessage(arbitration_id=0x456, data=b'\xAA\xBB\xCC\xDD')
        self.can.rx_fifo0.append(msg)
        self.can.rf0r = 1  # 1 message in FIFO

        # Read identifier
        rir = self.can.read(self.can.RI0R, 4)
        self.assertEqual((rir >> 21) & 0x7FF, 0x456)

        # Read DLC
        rdtr = self.can.read(self.can.RDT0R, 4)
        self.assertEqual(rdtr & 0xF, 4)

        # Read data
        rdlr = self.can.read(self.can.RDL0R, 4)
        self.assertEqual(rdlr, 0xDDCCBBAA)  # Little-endian

    def test_fifo_release(self):
        """Test releasing message from RX FIFO."""
        # Add message
        msg = CANMessage(arbitration_id=0x123, data=b'\x01')
        self.can.rx_fifo0.append(msg)
        self.can.rf0r = 1

        # Release FIFO (RFOM0 bit)
        self.can.write(self.can.RF0R, 4, (1 << 5))

        # Verify removed
        self.assertEqual(len(self.can.rx_fifo0), 0)


class TestSocketCANBackend(unittest.TestCase):
    """Test SocketCAN backend."""

    def test_message_packing(self):
        """Test CAN frame packing."""
        msg = CANMessage(
            arbitration_id=0x123,
            data=b'\x01\x02\x03\x04\x05\x06\x07\x08'
        )

        # Build frame manually
        can_id = msg.arbitration_id
        dlc = len(msg.data)
        data_padded = msg.data.ljust(8, b'\x00')
        frame = struct.pack('=IB3x8s', can_id, dlc, data_padded)

        self.assertEqual(len(frame), 16)
        self.assertEqual(struct.unpack('=I', frame[:4])[0], 0x123)

    def test_extended_id_flag(self):
        """Test extended ID flag in CAN frame."""
        msg = CANMessage(
            arbitration_id=0x12345,
            data=b'\x00',
            is_extended=True
        )

        can_id = msg.arbitration_id
        if msg.is_extended:
            can_id |= 0x80000000

        self.assertEqual(can_id & 0x80000000, 0x80000000)
        self.assertEqual(can_id & 0x1FFFFFFF, 0x12345)


# =============================================================================
# BLUETOOTH BRIDGE TESTS
# =============================================================================

class TestHCIPackets(unittest.TestCase):
    """Test HCI packet handling."""

    def test_hci_command_build(self):
        """Test building HCI command packet."""
        opcode = 0x0C03  # HCI_Reset
        params = b''

        packet = bytes([0x01])  # HCI_COMMAND type
        packet += struct.pack('<H', opcode)
        packet += bytes([len(params)])
        packet += params

        self.assertEqual(len(packet), 4)
        self.assertEqual(packet[0], 0x01)
        self.assertEqual(struct.unpack('<H', packet[1:3])[0], 0x0C03)

    def test_hci_event_parse(self):
        """Test parsing HCI event packet."""
        # Command Complete event
        packet = bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x00])

        pkt_type = packet[0]
        event_code = packet[1]
        param_len = packet[2]

        self.assertEqual(pkt_type, 0x04)  # HCI_EVENT
        self.assertEqual(event_code, 0x0E)  # Command Complete
        self.assertEqual(param_len, 4)


class TestNordicBLEController(unittest.TestCase):
    """Test Nordic BLE controller bridge."""

    def setUp(self):
        # Create controller without backend
        self.ble = NordicBLEController(backend=None)

    def test_initial_state(self):
        """Test initial BLE state."""
        self.assertFalse(self.ble.advertising)
        self.assertFalse(self.ble.scanning)
        self.assertFalse(self.ble.connected)

    def test_advertising_data_format(self):
        """Test BLE advertising data format."""
        # Standard advertising data format
        # Length (1) + Type (1) + Data (N)
        adv_data = bytes([
            0x02, 0x01, 0x06,  # Flags: LE General Discoverable
            0x09, 0x09, ord('M'), ord('C'), ord('U'), ord('e'), ord('m'), ord('u'), ord('B'), ord('T'),  # Complete Local Name
        ])

        self.assertLessEqual(len(adv_data), 31)  # Max advertising data length

    @patch.object(NordicBLEController, 'send_hci_command', new_callable=AsyncMock)
    def test_reset_command(self, mock_send):
        """Test HCI reset command."""
        mock_send.return_value = True

        async def run_test():
            result = await self.ble.reset()
            mock_send.assert_called_once_with(0x0C03)
            return result

        result = asyncio.run(run_test())
        self.assertTrue(result)


# =============================================================================
# FACTORY TESTS
# =============================================================================

class TestFactoryFunctions(unittest.TestCase):
    """Test factory functions."""

    def test_create_crypto_bridge(self):
        """Test crypto bridge factory."""
        crypto, hash_engine = create_crypto_bridge("stm32f4")
        self.assertIsInstance(crypto, STM32CryptoEngine)
        self.assertIsInstance(hash_engine, STM32HashEngine)

    def test_create_crypto_bridge_invalid(self):
        """Test crypto bridge factory with invalid SoC."""
        with self.assertRaises(ValueError):
            create_crypto_bridge("unknown_soc")

    def test_create_can_bridge_socketcan(self):
        """Test CAN bridge factory with SocketCAN."""
        can = create_can_bridge("vcan0", "socketcan")
        self.assertIsInstance(can, STM32CANController)
        self.assertIsInstance(can.backend, SocketCANBackend)

    def test_create_can_bridge_scapy(self):
        """Test CAN bridge factory with Scapy."""
        can = create_can_bridge("vcan0", "scapy")
        self.assertIsInstance(can, STM32CANController)
        self.assertIsInstance(can.backend, ScapyCANBackend)

    def test_create_can_bridge_invalid(self):
        """Test CAN bridge factory with invalid backend."""
        with self.assertRaises(ValueError):
            create_can_bridge("vcan0", "invalid")

    def test_create_bluetooth_bridge_hci(self):
        """Test Bluetooth bridge factory with HCI."""
        ble = create_bluetooth_bridge(0, "hci")
        self.assertIsInstance(ble, NordicBLEController)
        self.assertIsInstance(ble.backend, HCISocketBackend)

    def test_create_bluetooth_bridge_dbus(self):
        """Test Bluetooth bridge factory with D-Bus."""
        ble = create_bluetooth_bridge(0, "dbus")
        self.assertIsInstance(ble, NordicBLEController)
        self.assertIsInstance(ble.backend, BlueZDBusBackend)


# =============================================================================
# INTEGRATION TESTS (require hardware)
# =============================================================================

class TestCryptoIntegration(unittest.TestCase):
    """Integration tests for crypto (requires cryptography library)."""

    def test_aes_encrypt_decrypt_roundtrip(self):
        """Test AES encryption/decryption roundtrip."""
        crypto_enc = STM32CryptoEngine()
        crypto_dec = STM32CryptoEngine()

        if not crypto_enc._openssl_available:
            self.skipTest("cryptography library not available")

        # Use same key for both
        key = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F]
        for i, word in enumerate(key):
            crypto_enc.write(crypto_enc.K0LR + i*4, 4, word)
            crypto_dec.write(crypto_dec.K0LR + i*4, 4, word)

        # Set up encryptor
        cr_enc = (STM32CryptoAlgorithm.AES_ECB << 3) | crypto_enc.CR_CRYPEN
        crypto_enc.write(crypto_enc.CR, 4, cr_enc)

        # Set up decryptor (with ALGODIR bit for decrypt)
        cr_dec = (STM32CryptoAlgorithm.AES_ECB << 3) | crypto_dec.CR_CRYPEN | crypto_dec.CR_ALGODIR
        crypto_dec.write(crypto_dec.CR, 4, cr_dec)

        # Original plaintext
        plaintext = [0xDEADBEEF, 0xCAFEBABE, 0x12345678, 0x9ABCDEF0]

        # Encrypt
        for word in plaintext:
            crypto_enc.write(crypto_enc.DIN, 4, word)
        ciphertext = [crypto_enc.read(crypto_enc.DOUT, 4) for _ in range(4)]

        # Decrypt
        for word in ciphertext:
            crypto_dec.write(crypto_dec.DIN, 4, word)
        decrypted = [crypto_dec.read(crypto_dec.DOUT, 4) for _ in range(4)]

        # Verify roundtrip
        self.assertEqual(plaintext, decrypted)


# =============================================================================
# MAIN
# =============================================================================

def run_tests():
    """Run all tests."""
    print("=" * 60)
    print("MCUemu Peripheral Bridges Test Suite")
    print("=" * 60)

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestSTM32CryptoEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestSTM32HashEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestCANMessage))
    suite.addTests(loader.loadTestsFromTestCase(TestSTM32CANController))
    suite.addTests(loader.loadTestsFromTestCase(TestSocketCANBackend))
    suite.addTests(loader.loadTestsFromTestCase(TestHCIPackets))
    suite.addTests(loader.loadTestsFromTestCase(TestNordicBLEController))
    suite.addTests(loader.loadTestsFromTestCase(TestFactoryFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestCryptoIntegration))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.wasSuccessful():
        print("\nAll tests PASSED!")
        return 0
    else:
        print("\nSome tests FAILED!")
        return 1


if __name__ == '__main__':
    sys.exit(run_tests())
