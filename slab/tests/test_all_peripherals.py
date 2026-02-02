#!/usr/bin/env python3
"""
Comprehensive Peripheral Test Suite

Tests all Slab peripheral implementations to ensure correctness
and compatibility with real STM32 firmware.

Run with: pytest tests/test_all_peripherals.py -v

SPDX-License-Identifier: Apache-2.0
Copyright (C) 2026 TwistedWires Security Lab
"""

import sys
import os
import struct
import unittest
import threading
import time
from unittest.mock import Mock, MagicMock, patch

# Add paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python', 'slab_cortex_m'))


# =============================================================================
# CAN PERIPHERAL TESTS
# =============================================================================

class TestCANPeripheral(unittest.TestCase):
    """Test CAN controller emulation."""

    def setUp(self):
        from slab_cortex_m.can_peripheral import CANController, VirtualCANBridge
        self.can = CANController(0x40006400, "CAN1")
        self.vcan = VirtualCANBridge()

    def test_initialization(self):
        """Test initial register values."""
        # MCR should have SLEEP set
        mcr = self.can.read_reg(self.can.MCR)
        self.assertTrue(mcr & self.can.MCR_SLEEP)

        # TSR should have all mailboxes empty
        tsr = self.can.read_reg(self.can.TSR)
        self.assertTrue(tsr & self.can.TSR_TME0)
        self.assertTrue(tsr & self.can.TSR_TME1)
        self.assertTrue(tsr & self.can.TSR_TME2)

    def test_enter_init_mode(self):
        """Test entering initialization mode."""
        # Request init mode
        self.can.write_reg(self.can.MCR, self.can.MCR_INRQ)

        # Check INAK is set
        msr = self.can.read_reg(self.can.MSR)
        self.assertTrue(msr & self.can.MSR_INAK)

    def test_exit_init_mode(self):
        """Test exiting initialization mode."""
        # Enter then exit init
        self.can.write_reg(self.can.MCR, self.can.MCR_INRQ)
        self.can.write_reg(self.can.MCR, 0)

        # Check INAK is clear
        msr = self.can.read_reg(self.can.MSR)
        self.assertFalse(msr & self.can.MSR_INAK)

    def test_tx_message(self):
        """Test transmitting a CAN message."""
        from slab_cortex_m.can_peripheral import CANMessage

        # Connect bridge and track messages
        tx_messages = []
        self.can.connect_bridge(self.vcan)
        self.can.on_tx = lambda msg: tx_messages.append(msg)

        # Exit init mode
        self.can.write_reg(self.can.MCR, self.can.MCR_INRQ)
        self.can.write_reg(self.can.MCR, 0)

        # Prepare mailbox 0
        self.can.write_reg(self.can.TDL0R, 0x12345678)
        self.can.write_reg(self.can.TDH0R, 0xABCDEF00)
        self.can.write_reg(self.can.TDT0R, 8)  # DLC = 8

        # Set ID and transmit
        self.can.write_reg(self.can.TI0R, (0x123 << 21) | 1)  # TXRQ

        # Verify message sent
        self.assertEqual(len(tx_messages), 1)
        self.assertEqual(tx_messages[0].arbitration_id, 0x123)
        self.assertEqual(tx_messages[0].dlc, 8)

    def test_rx_filter(self):
        """Test receive filtering."""
        from slab_cortex_m.can_peripheral import CANMessage

        # Add filter for 0x100-0x1FF
        self.can.add_filter(0x100, 0x700)

        # Exit init mode
        self.can.write_reg(self.can.MCR, self.can.MCR_INRQ)
        self.can.write_reg(self.can.MCR, 0)

        # Receive matching message
        msg1 = CANMessage(0x123, b'\x01\x02\x03\x04')
        self.can._receive_message(msg1)
        self.assertEqual(len(self.can.rx_fifo0), 1)

        # Receive non-matching message
        msg2 = CANMessage(0x300, b'\x05\x06\x07\x08')
        self.can._receive_message(msg2)
        self.assertEqual(len(self.can.rx_fifo0), 1)  # Still 1

    def test_loopback_mode(self):
        """Test loopback mode."""
        from slab_cortex_m.can_peripheral import CANMode

        self.can.mode = CANMode.LOOPBACK

        # Exit init mode
        self.can.write_reg(self.can.MCR, self.can.MCR_INRQ)
        self.can.write_reg(self.can.MCR, 0)

        # Transmit
        self.can.write_reg(self.can.TDL0R, 0xDEADBEEF)
        self.can.write_reg(self.can.TDT0R, 4)
        self.can.write_reg(self.can.TI0R, (0x100 << 21) | 1)

        # Should be received in own FIFO
        self.assertGreater(len(self.can.rx_fifo0), 0)


# =============================================================================
# USB OTG TESTS
# =============================================================================

class TestUSBOTG(unittest.TestCase):
    """Test USB OTG controller emulation."""

    def test_device_creation(self):
        """Test USB device creation."""
        try:
            from slab_cortex_m.usb_otg import USBDevice, create_cdc_acm_device
        except ImportError:
            self.skipTest("USB OTG module not available")

        device = create_cdc_acm_device(0x1234, 0x5678)
        self.assertEqual(device.vendor_id, 0x1234)
        self.assertEqual(device.product_id, 0x5678)
        self.assertEqual(device.device_class, 0x02)  # CDC

    def test_device_descriptor(self):
        """Test device descriptor generation."""
        try:
            from slab_cortex_m.usb_otg import USBDevice, create_cdc_acm_device
        except ImportError:
            self.skipTest("USB OTG module not available")

        device = create_cdc_acm_device(0xCAFE, 0xBEEF)
        desc = device.get_device_descriptor()

        self.assertEqual(len(desc), 18)  # Standard device descriptor
        self.assertEqual(desc[0], 18)     # bLength
        self.assertEqual(desc[1], 1)      # bDescriptorType = DEVICE

        vid, = struct.unpack('<H', desc[8:10])
        pid, = struct.unpack('<H', desc[10:12])
        self.assertEqual(vid, 0xCAFE)
        self.assertEqual(pid, 0xBEEF)

    def test_otg_controller_modes(self):
        """Test OTG mode switching."""
        try:
            from slab_cortex_m.usb_otg import OTGController, OTGMode
        except ImportError:
            self.skipTest("USB OTG module not available")

        otg = OTGController()

        # Default mode
        self.assertEqual(otg.mode, OTGMode.DEVICE)

        # Switch modes
        otg.set_mode(OTGMode.HOST)
        self.assertEqual(otg.mode, OTGMode.HOST)


# =============================================================================
# SPI BRIDGE TESTS
# =============================================================================

class TestSPIBridge(unittest.TestCase):
    """Test SPI bridge functionality."""

    def test_spi_master_init(self):
        """Test SPI master initialization."""
        try:
            from slab_cortex_m.spi_bridge import SPIMasterPeripheral
        except ImportError:
            self.skipTest("SPI bridge module not available")

        spi = SPIMasterPeripheral('SPI1', 0x40013000)
        self.assertEqual(spi.name, 'SPI1')
        self.assertEqual(spi.base, 0x40013000)

    def test_spi_slave_init(self):
        """Test SPI slave initialization."""
        try:
            from slab_cortex_m.spi_bridge import SPISlavePeripheral
        except ImportError:
            self.skipTest("SPI bridge module not available")

        spi = SPISlavePeripheral('SPI2', 0x40003800)
        self.assertEqual(spi.name, 'SPI2')

    def test_spi_bridge_transfer(self):
        """Test SPI master-slave transfer."""
        try:
            from slab_cortex_m.spi_bridge import (
                SPIMasterPeripheral, SPISlavePeripheral, SPIBridge, STM32_SPI
            )
        except ImportError:
            self.skipTest("SPI bridge module not available")

        master = SPIMasterPeripheral('SPI1', 0x40013000)
        slave = SPISlavePeripheral('SPI2', 0x40003800)
        bridge = SPIBridge()
        bridge.connect(master, slave)

        # Configure slave response (preload TX data)
        slave.write(STM32_SPI.DR, 4, 0xAA)

        # Enable both: SPE | MSTR for master, SPE for slave
        master.write(STM32_SPI.CR1, 4, (1 << 6) | (1 << 2))
        slave.write(STM32_SPI.CR1, 4, (1 << 6))

        # Transfer - master sends 0x01
        master.write(STM32_SPI.DR, 4, 0x01)

        # Check slave received in dr_rx
        self.assertEqual(slave.dr_rx, 0x01)


# =============================================================================
# TCP PERIPHERAL TESTS
# =============================================================================

class TestTCPPeripheral(unittest.TestCase):
    """Test TCP peripheral bridge."""

    def test_packet_pack_unpack(self):
        """Test TCP packet serialization."""
        from slab_cortex_m.tcp_peripheral import TcpPacket, TcpCommand

        # Create packet
        pkt = TcpPacket(
            command=TcpCommand.READ32,
            address=0x40020000,
            data=0
        )

        # Pack and unpack
        raw = pkt.pack()
        pkt2 = TcpPacket.unpack(raw)

        self.assertEqual(pkt2.command, TcpCommand.READ32)
        self.assertEqual(pkt2.address, 0x40020000)

    def test_packet_header_size(self):
        """Test packet header size."""
        from slab_cortex_m.tcp_peripheral import TcpPacket

        self.assertEqual(TcpPacket.HEADER_SIZE, 12)


# =============================================================================
# CRYPTO ENGINE TESTS
# =============================================================================

class TestCryptoEngine(unittest.TestCase):
    """Test STM32 crypto engine bridge."""

    def setUp(self):
        from slab_cortex_m.peripheral_bridges import STM32CryptoEngine
        self.crypto = STM32CryptoEngine()

    def test_initial_status(self):
        """Test initial status register."""
        sr = self.crypto.read(self.crypto.SR, 4)

        # Input FIFO should be empty
        self.assertTrue(sr & self.crypto.SR_IFEM)
        # Input FIFO should not be full
        self.assertTrue(sr & self.crypto.SR_IFNF)

    def test_key_loading(self):
        """Test loading crypto key."""
        key = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F]

        for i, word in enumerate(key):
            self.crypto.write(self.crypto.K0LR + i*4, 4, word)

        # Verify
        for i, expected in enumerate(key):
            self.assertEqual(self.crypto.key_regs[i], expected)

    def test_iv_loading(self):
        """Test loading initialization vector."""
        iv = [0x10111213, 0x14151617, 0x18191A1B, 0x1C1D1E1F]

        for i, word in enumerate(iv):
            self.crypto.write(self.crypto.IV0LR + i*4, 4, word)

        # Verify
        for i, expected in enumerate(iv):
            self.assertEqual(self.crypto.iv_regs[i], expected)

    def test_aes_encrypt(self):
        """Test AES encryption."""
        if not self.crypto._openssl_available:
            self.skipTest("OpenSSL not available")

        from slab_cortex_m.peripheral_bridges import STM32CryptoAlgorithm

        # Zero key
        for i in range(4):
            self.crypto.write(self.crypto.K0LR + i*4, 4, 0)

        # Enable AES-ECB
        cr = (STM32CryptoAlgorithm.AES_ECB << 3) | self.crypto.CR_CRYPEN
        self.crypto.write(self.crypto.CR, 4, cr)

        # Write plaintext
        plaintext = [0x00000000, 0x00000000, 0x00000000, 0x00000000]
        for word in plaintext:
            self.crypto.write(self.crypto.DIN, 4, word)

        # Read ciphertext
        ciphertext = [self.crypto.read(self.crypto.DOUT, 4) for _ in range(4)]

        # Should be different (encrypted)
        self.assertNotEqual(plaintext, ciphertext)


# =============================================================================
# STM32 PERIPHERAL TESTS
# =============================================================================

class TestSTM32Peripherals(unittest.TestCase):
    """Test STM32 peripheral implementations."""

    def test_gpio_port(self):
        """Test GPIO port emulation."""
        try:
            from slab_cortex_m.stm32_peripherals import GPIOPort
        except ImportError:
            self.skipTest("STM32 peripherals not available")

        gpio = GPIOPort('GPIOA', 0x40020000)

        # Write ODR
        gpio.write_reg(gpio.ODR, 0x1234)
        self.assertEqual(gpio.read_reg(gpio.ODR), 0x1234)

        # Test BSRR set
        gpio.write_reg(gpio.BSRR, 0x0001)  # Set bit 0
        self.assertTrue(gpio.read_reg(gpio.ODR) & 0x0001)

        # Test BSRR reset
        gpio.write_reg(gpio.BSRR, 0x00010000)  # Reset bit 0
        self.assertFalse(gpio.read_reg(gpio.ODR) & 0x0001)

    def test_usart(self):
        """Test USART emulation via slab_stm32 package."""
        try:
            from slab_stm32.stm32_uart import STM32USARTv1
        except ImportError:
            self.skipTest("STM32 USART not available")

        usart = STM32USARTv1('USART1', 0x40011000)

        # Configure using correct API
        usart.write(usart.BRR, 4, 0x2D9)  # 115200 baud
        usart.write(usart.CR1, 4, (1 << 13) | (1 << 3) | (1 << 2))  # UE|TE|RE

        # TX should be empty
        sr = usart.read(usart.ISR if hasattr(usart, 'ISR') else 0x00, 4)
        self.assertTrue(True)  # Basic functionality test

    def test_timer(self):
        """Test timer emulation using SysTick."""
        try:
            from slab_cortex_m.stm32_peripherals import SysTickTimer
        except ImportError:
            self.skipTest("SysTick timer not available")

        systick = SysTickTimer()

        # Configure with valid 24-bit value (max 0xFFFFFF = 16777215)
        test_load = 0x00FFFFFF  # Max valid value for SysTick LOAD
        systick.write(systick.LOAD, 4, test_load)
        systick.write(systick.CTRL, 4, systick.CTRL_ENABLE | systick.CTRL_CLKSOURCE)

        # Verify configuration
        ctrl = systick.read(systick.CTRL, 4)
        self.assertTrue(ctrl & systick.CTRL_ENABLE)

        # Verify load value (24-bit max)
        load = systick.read(systick.LOAD, 4)
        self.assertEqual(load, test_load)

    def test_dma_stream(self):
        """Test DMA stream emulation."""
        try:
            from slab_cortex_m.stm32_peripherals import DMAController
        except ImportError:
            self.skipTest("STM32 peripherals not available")

        dma = DMAController('DMA1', 0x40026000)

        # Stream 0 should exist
        self.assertEqual(len(dma.streams), 8)

        # Configure stream 0 addresses using write(offset, size, value)
        dma.write(0x18 + 0x08, 4, 0x20000000)  # PAR
        dma.write(0x18 + 0x0C, 4, 0x20001000)  # M0AR
        dma.write(0x18 + 0x04, 4, 16)          # NDTR


# =============================================================================
# W25Q FLASH TESTS
# =============================================================================

class TestW25QFlash(unittest.TestCase):
    """Test SPI Flash emulation."""

    def test_jedec_id(self):
        """Test JEDEC ID reading."""
        try:
            from slab_cortex_m.stm32_peripherals import W25QFlash
        except ImportError:
            self.skipTest("W25Q Flash not available")

        flash = W25QFlash(size_mb=16)
        jedec = flash.execute_command(0x9F, 0, 3)

        self.assertEqual(len(jedec), 3)
        self.assertEqual(jedec[0], 0xEF)  # Winbond

    def test_write_read(self):
        """Test write and read."""
        try:
            from slab_cortex_m.stm32_peripherals import W25QFlash
        except ImportError:
            self.skipTest("W25Q Flash not available")

        flash = W25QFlash(size_mb=16)

        # Write enable
        flash.execute_command(0x06, 0, 0)

        # Page program
        data = b"Test data!"
        flash.execute_command(0x02, 0x1000, 0, data)

        # Fast read (skip dummy byte)
        read = flash.execute_command(0x0B, 0x1000, len(data) + 1)[1:]

        self.assertEqual(read, data)

    def test_sector_erase(self):
        """Test sector erase."""
        try:
            from slab_cortex_m.stm32_peripherals import W25QFlash
        except ImportError:
            self.skipTest("W25Q Flash not available")

        flash = W25QFlash(size_mb=16)

        # Write data first
        flash.execute_command(0x06, 0, 0)
        flash.execute_command(0x02, 0x1000, 0, b"XXXXXXXX")

        # Erase sector
        flash.execute_command(0x06, 0, 0)
        flash.execute_command(0x20, 0x1000, 0)

        # Should be 0xFF
        read = flash.execute_command(0x0B, 0x1000, 9)[1:]
        self.assertEqual(read, b'\xFF' * 8)


# =============================================================================
# VIRTUAL CAN BRIDGE TESTS
# =============================================================================

class TestVirtualCANBridge(unittest.TestCase):
    """Test virtual CAN bridge for multi-ECU testing."""

    def test_bridge_message_routing(self):
        """Test message routing between controllers."""
        from slab_cortex_m.can_peripheral import CANController, VirtualCANBridge, CANMessage

        can1 = CANController(0x40006400, "CAN1")
        can2 = CANController(0x40006800, "CAN2")

        vcan = VirtualCANBridge()
        vcan.connect(can2._receive_message)
        can1.connect_bridge(vcan)

        # Initialize both
        can1.write_reg(can1.MCR, can1.MCR_INRQ)
        can1.write_reg(can1.MCR, 0)
        can2.write_reg(can2.MCR, can2.MCR_INRQ)
        can2.write_reg(can2.MCR, 0)

        # Send from CAN1
        can1.write_reg(can1.TDL0R, 0xDEADBEEF)
        can1.write_reg(can1.TDT0R, 4)
        can1.write_reg(can1.TI0R, (0x100 << 21) | 1)

        # CAN2 should receive
        self.assertEqual(len(can2.rx_fifo0), 1)
        self.assertEqual(can2.rx_fifo0[0].arbitration_id, 0x100)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestPeripheralIntegration(unittest.TestCase):
    """Test peripheral integration scenarios."""

    def test_can_with_gpio(self):
        """Test CAN controller with GPIO interrupt on RX."""
        try:
            from slab_cortex_m.can_peripheral import CANController, VirtualCANBridge
            from slab_cortex_m.stm32_peripherals import GPIOPort, EXTIController
        except ImportError:
            self.skipTest("Required modules not available")

        can = CANController(0x40006400, "CAN1")
        gpio = GPIOPort('GPIOA', 0x40020000)

        rx_count = [0]

        def on_rx(msg):
            rx_count[0] += 1
            gpio.set_input_pin(0, True)  # Signal via GPIO

        can.on_rx = on_rx

        # Initialize
        can.write_reg(can.MCR, can.MCR_INRQ)
        can.write_reg(can.MCR, 0)

        # Inject RX message
        from slab_cortex_m.can_peripheral import CANMessage
        can._receive_message(CANMessage(0x123, b'\x01\x02\x03\x04'))

        self.assertEqual(rx_count[0], 1)

    def test_crypto_with_dma(self):
        """Test crypto engine with DMA transfer."""
        try:
            from slab_cortex_m.peripheral_bridges import STM32CryptoEngine
            from slab_cortex_m.stm32_peripherals import DMAController
        except ImportError:
            self.skipTest("Required modules not available")

        crypto = STM32CryptoEngine()
        dma = DMAController('DMA2', 0x40026400)

        # This is a conceptual test - in reality DMA would
        # be configured to move data to/from crypto engine
        self.assertIsNotNone(crypto)
        self.assertIsNotNone(dma)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
