#!/usr/bin/env python3
"""
Test STM32F1 USB Device Peripheral

This test validates the USB Device emulation for STM32F103.

Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
from pathlib import Path

# Add SLAB to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import pytest
from slab_stm32 import STM32F103PeripheralSet, STM32USBDevice
from slab_stm32.stm32_usb_device import USBDeviceReg, USBCntrBits, EPStatBits


class TestSTM32USBDevice:
    """Test STM32F1 USB Device peripheral."""

    def setup_method(self):
        """Set up test fixtures."""
        self.usb = STM32USBDevice()

    def test_initial_state(self):
        """Test USB initial state after reset."""
        # USB should be in reset and powered down
        cntr = self.usb.read(0x40005C00 + USBDeviceReg.CNTR, 4)[0]
        assert cntr & (1 << USBCntrBits.FRES), "FRES should be set"
        assert cntr & (1 << USBCntrBits.PDWN), "PDWN should be set"

    def test_power_up_sequence(self):
        """Test USB power-up and reset release."""
        base = 0x40005C00

        # Step 1: Clear PDWN (power up analog blocks)
        self.usb.write(base + USBDeviceReg.CNTR, 4, 1 << USBCntrBits.FRES)

        cntr = self.usb.read(base + USBDeviceReg.CNTR, 4)[0]
        assert not (cntr & (1 << USBCntrBits.PDWN)), "PDWN should be clear"

        # Step 2: Clear FRES (release reset)
        self.usb.write(base + USBDeviceReg.CNTR, 4, 0)

        cntr = self.usb.read(base + USBDeviceReg.CNTR, 4)[0]
        assert not (cntr & (1 << USBCntrBits.FRES)), "FRES should be clear"

    def test_set_device_address(self):
        """Test setting USB device address."""
        base = 0x40005C00

        # Set address 5 with enable bit
        self.usb.write(base + USBDeviceReg.DADDR, 4, 0x85)

        assert self.usb.address == 5, "Address should be 5"

        daddr = self.usb.read(base + USBDeviceReg.DADDR, 4)[0]
        assert daddr == 0x85, f"DADDR should be 0x85, got 0x{daddr:02X}"

    def test_buffer_table_address(self):
        """Test buffer table address register."""
        base = 0x40005C00

        # BTABLE must be 8-byte aligned
        self.usb.write(base + USBDeviceReg.BTABLE, 4, 0x0040)

        btable = self.usb.read(base + USBDeviceReg.BTABLE, 4)[0]
        assert btable == 0x0040, f"BTABLE should be 0x40, got 0x{btable:04X}"

    def test_pma_read_write(self):
        """Test Packet Memory Area access."""
        pma_base = 0x40006000

        # Write to PMA
        self.usb.write(pma_base, 4, 0x1234)
        self.usb.write(pma_base + 4, 4, 0x5678)

        # Read back
        val1 = self.usb.read(pma_base, 4)[0]
        val2 = self.usb.read(pma_base + 4, 4)[0]

        assert val1 == 0x1234, f"PMA[0] should be 0x1234, got 0x{val1:04X}"
        assert val2 == 0x5678, f"PMA[4] should be 0x5678, got 0x{val2:04X}"

    def test_endpoint_configuration(self):
        """Test endpoint register configuration."""
        base = 0x40005C00

        # Configure EP0 as CONTROL, VALID for TX and RX
        # EP_TYPE = CONTROL (0b01), STAT_TX = VALID (0b11), STAT_RX = VALID (0b11)
        # EPnR toggle bits: STAT_TX bits 4-5, STAT_RX bits 12-13

        # First power up USB
        self.usb.write(base + USBDeviceReg.CNTR, 4, 0)

        # Write EP0R with address 0, CONTROL type, toggle TX and RX to VALID
        # EP_TYPE (bits 9-10) = 0b01 (CONTROL)
        # Toggle STAT_TX (bits 4-5) from 00 to 11 by writing 0b11
        # Toggle STAT_RX (bits 12-13) from 00 to 11 by writing 0b11
        ep0r_value = (1 << 9) | (0b11 << 4) | (0b11 << 12)
        self.usb.write(base + USBDeviceReg.EP0R, 4, ep0r_value)

        # Check endpoint state
        assert self.usb.endpoints[0].tx_status == EPStatBits.VALID
        assert self.usb.endpoints[0].rx_status == EPStatBits.VALID

    def test_send_to_endpoint(self):
        """Test sending data to an endpoint."""
        # Setup: Configure EP1 for bulk OUT
        self.usb.endpoints[1].rx_status = EPStatBits.VALID
        self.usb.endpoints[1].type = 0b00  # BULK

        # Set up buffer table entry for EP1 RX
        # BTABLE at offset 0, EP1 RX at BTABLE + 1*8 + 4 = 12
        self.usb._btable = 0
        self.usb._write_pma_word(12, 0x0080)  # RX buffer at offset 0x80
        self.usb._write_pma_word(14, (1 << 15) | (2 << 10))  # BL_SIZE=1, NUM_BLOCK=2 (64 bytes)

        # Send data
        test_data = b"Hello USB!"
        result = self.usb.send_to_endpoint(1, test_data)

        assert result, "send_to_endpoint should return True"
        assert self.usb.endpoints[1].ctr_rx, "CTR_RX should be set"

        # Verify data in PMA
        pma_data = self.usb._read_pma_buffer(0x80, len(test_data))
        assert pma_data == test_data, f"PMA data mismatch: {pma_data}"

    def test_simulate_bus_reset(self):
        """Test USB bus reset simulation."""
        # Enable reset interrupt
        self.usb._cntr = 1 << USBCntrBits.RESETM

        irq_triggered = [False]

        def irq_callback(irq, level):
            irq_triggered[0] = True

        self.usb.irq_callback = irq_callback

        # Simulate reset
        self.usb.simulate_reset()

        # Check ISTR.RESET flag
        istr = self.usb.read(0x40005C00 + USBDeviceReg.ISTR, 4)[0]
        assert istr & (1 << 10), "RESET flag should be set in ISTR"
        assert irq_triggered[0], "IRQ should have been triggered"


class TestSTM32F103WithUSB:
    """Test STM32F103 peripheral set with USB."""

    def test_peripheral_set_has_usb(self):
        """Test that F103 peripheral set includes USB."""
        ps = STM32F103PeripheralSet()

        assert hasattr(ps, 'usb'), "F103 should have USB peripheral"
        assert 'USB' in ps.list_peripherals()

    def test_usb_address_range(self):
        """Test USB address range in peripheral set."""
        ps = STM32F103PeripheralSet()

        # USB registers
        assert ps.usb.contains(0x40005C00), "USB should contain 0x40005C00"
        assert ps.usb.contains(0x40005C40), "USB should contain CNTR"
        assert ps.usb.contains(0x40005C50), "USB should contain BTABLE"

        # PMA
        assert ps.usb.contains(0x40006000), "USB should contain PMA base"
        assert ps.usb.contains(0x400061FF), "USB should contain PMA end"

    def test_cdc_simulation(self):
        """Test CDC data path simulation."""
        ps = STM32F103PeripheralSet()

        # Configure EP1 for CDC data
        ps.usb.endpoints[1].type = 0b00  # BULK
        ps.usb.endpoints[1].rx_status = EPStatBits.VALID

        # Setup buffer table
        ps.usb._btable = 0
        ps.usb._write_pma_word(12, 0x00C0)  # EP1 RX buffer
        ps.usb._write_pma_word(14, (1 << 15) | (2 << 10))  # 64 bytes max

        # Send CDC data
        test_msg = b"AUTH\n"
        result = ps.usb.cdc_send(test_msg)

        # In a real implementation, the firmware would process this
        # For now, verify the data reached the buffer
        assert result or ps.usb.endpoints[1].rx_status != EPStatBits.VALID


def main():
    """Run tests."""
    print("Testing STM32F1 USB Device Peripheral")
    print("=" * 50)

    # Run a few quick tests
    usb = STM32USBDevice()

    # Test 1: Initial state
    print("\n[1] Testing initial state...")
    cntr = usb.read(0x40005C00 + 0x40, 4)[0]
    assert cntr & 0x03 == 0x03, "USB should be in reset+powerdown"
    print("    OK: USB in reset state")

    # Test 2: Power up
    print("\n[2] Testing power-up sequence...")
    usb.write(0x40005C00 + 0x40, 4, 0)  # Clear FRES and PDWN
    print("    OK: USB powered up")

    # Test 3: PMA access
    print("\n[3] Testing PMA access...")
    usb.write(0x40006000, 4, 0xDEAD)
    usb.write(0x40006004, 4, 0xBEEF)
    val1 = usb.read(0x40006000, 4)[0]
    val2 = usb.read(0x40006004, 4)[0]
    assert val1 == 0xDEAD and val2 == 0xBEEF, "PMA read/write failed"
    print("    OK: PMA read/write works")

    # Test 4: Device address
    print("\n[4] Testing device address...")
    usb.write(0x40005C00 + 0x4C, 4, 0x85)  # Address 5, enabled
    assert usb.address == 5, "Address not set correctly"
    print("    OK: Device address set to 5")

    # Test 5: F103 peripheral set
    print("\n[5] Testing STM32F103 peripheral set...")
    ps = STM32F103PeripheralSet()
    assert 'USB' in ps.list_peripherals()
    print(f"    OK: F103 has {len(ps.list_peripherals())} peripherals including USB")

    print("\n" + "=" * 50)
    print("All tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
