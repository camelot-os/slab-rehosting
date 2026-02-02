#!/usr/bin/env python3
"""
Hardware-in-the-Loop (HIL) Test for MCUemu

This test demonstrates the HIL capability by running a mock hardware server
and verifying that the HIL peripheral correctly forwards accesses.

Usage:
    python3 test_hil.py

Author: TwistedWires Security Lab
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

from hil_peripheral import HILTCPPeripheral, HILResponse


# =============================================================================
# MOCK HARDWARE SERVER
# =============================================================================

class MockHardwareServer:
    """
    Simulates real hardware for HIL testing.

    This server implements the MCUemu TCP protocol and responds to
    peripheral accesses as if it were real hardware.
    """

    def __init__(self, port: int = 5001):
        self.port = port
        self.server = None
        self.running = False

        # Simulated peripheral registers (STM32F4 GPIOA)
        self.registers = {
            0x40020000: 0xA8000000,  # MODER
            0x40020004: 0x00000000,  # OTYPER
            0x40020008: 0x0C000000,  # OSPEEDR
            0x4002000C: 0x64000000,  # PUPDR
            0x40020010: 0x00000000,  # IDR (input)
            0x40020014: 0x00000000,  # ODR (output)
            0x40020018: 0x00000000,  # BSRR
            0x4002001C: 0x00000000,  # LCKR
            0x40020020: 0x00000000,  # AFRL
            0x40020024: 0x00000000,  # AFRH
        }

    async def handle_client(self, reader, writer):
        """Handle client connection."""
        addr = writer.get_extra_info('peername')
        print(f"[MockHW] Client connected: {addr}")

        try:
            while self.running:
                # Read command byte
                cmd = await reader.read(1)
                if not cmd:
                    break

                if cmd == b'R':
                    # Read request: addr(4) + size(4) + secure(1)
                    data = await reader.read(9)
                    if len(data) < 9:
                        break
                    addr_val, size, secure = struct.unpack('<IIB', data)

                    # Return register value or 0 for unknown
                    value = self.registers.get(addr_val, 0)
                    print(f"[MockHW] Read 0x{addr_val:08X} = 0x{value:08X}")

                    # Send response: value(4) + status(1)
                    response = struct.pack('<IB', value, 0)
                    writer.write(response)
                    await writer.drain()

                elif cmd == b'W':
                    # Write request: addr(4) + size(4) + value(4) + secure(1)
                    data = await reader.read(13)
                    if len(data) < 13:
                        break
                    addr_val, size, value, secure = struct.unpack('<IIIB', data)

                    # Store register value
                    self.registers[addr_val] = value
                    print(f"[MockHW] Write 0x{addr_val:08X} <- 0x{value:08X}")

                    # Handle BSRR (bit set/reset register)
                    if addr_val == 0x40020018:
                        odr = self.registers.get(0x40020014, 0)
                        set_bits = value & 0xFFFF
                        reset_bits = (value >> 16) & 0xFFFF
                        odr = (odr | set_bits) & ~reset_bits
                        self.registers[0x40020014] = odr

                    # Send response: value(4) + status(1)
                    response = struct.pack('<IB', value, 0)
                    writer.write(response)
                    await writer.drain()

        except Exception as e:
            print(f"[MockHW] Error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            print("[MockHW] Client disconnected")

    async def start(self):
        """Start the mock hardware server."""
        self.running = True
        self.server = await asyncio.start_server(
            self.handle_client, 'localhost', self.port
        )
        print(f"[MockHW] Server started on port {self.port}")

    async def stop(self):
        """Stop the mock hardware server."""
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        print("[MockHW] Server stopped")


# =============================================================================
# TEST CASES
# =============================================================================

async def test_basic_read_write():
    """Test basic HIL read/write operations."""
    print("\n=== Test: Basic Read/Write ===")

    # Create mock hardware server
    mock_hw = MockHardwareServer(port=5001)
    await mock_hw.start()
    await asyncio.sleep(0.1)

    try:
        # Create HIL peripheral
        hil = HILTCPPeripheral(
            name="GPIOA_HIL",
            base=0x40020000,
            size=0x400,
            port=5001
        )

        # Connect
        assert await hil.connect(), "Failed to connect to mock hardware"

        # Test read
        value = await hil.read(0x40020000, 4)  # MODER
        print(f"Read MODER = 0x{value:08X}")
        assert value == 0xA8000000, f"Expected 0xA8000000, got 0x{value:08X}"

        # Test write
        await hil.write(0x40020014, 4, 0x00FF)  # ODR
        print("Wrote 0x00FF to ODR")

        # Read back
        value = await hil.read(0x40020014, 4)
        print(f"Read back ODR = 0x{value:08X}")
        assert value == 0x00FF, f"Expected 0x00FF, got 0x{value:08X}"

        # Disconnect
        await hil.disconnect()
        print("PASS: Basic read/write test")
        return True

    except AssertionError as e:
        print(f"FAIL: {e}")
        return False
    finally:
        await mock_hw.stop()


async def test_bsrr_operation():
    """Test GPIO BSRR (bit set/reset) operation."""
    print("\n=== Test: BSRR Operation ===")

    mock_hw = MockHardwareServer(port=5002)
    await mock_hw.start()
    await asyncio.sleep(0.1)

    try:
        hil = HILTCPPeripheral(
            name="GPIOA_HIL",
            base=0x40020000,
            size=0x400,
            port=5002
        )

        assert await hil.connect()

        # Set bits 0-3
        await hil.write(0x40020018, 4, 0x000F)  # BSRR: set bits 0-3
        value = await hil.read(0x40020014, 4)   # Read ODR
        print(f"After BSRR set 0-3: ODR = 0x{value:08X}")
        assert value == 0x000F, f"Expected 0x000F, got 0x{value:08X}"

        # Reset bits 0-1, set bits 4-5
        await hil.write(0x40020018, 4, 0x00030030)  # BSRR: reset 0-1, set 4-5
        value = await hil.read(0x40020014, 4)
        print(f"After BSRR reset 0-1, set 4-5: ODR = 0x{value:08X}")
        assert value == 0x003C, f"Expected 0x003C, got 0x{value:08X}"

        await hil.disconnect()
        print("PASS: BSRR operation test")
        return True

    except AssertionError as e:
        print(f"FAIL: {e}")
        return False
    finally:
        await mock_hw.stop()


async def test_multiple_peripherals():
    """Test multiple HIL peripherals to same server."""
    print("\n=== Test: Multiple Peripherals ===")

    mock_hw = MockHardwareServer(port=5003)
    # Add GPIOB registers
    mock_hw.registers.update({
        0x40020400: 0x00000280,  # GPIOB MODER
        0x40020414: 0x00000000,  # GPIOB ODR
    })
    await mock_hw.start()
    await asyncio.sleep(0.1)

    try:
        # Create two HIL peripherals for GPIOA and GPIOB
        gpioa = HILTCPPeripheral("GPIOA", 0x40020000, 0x400, port=5003)
        gpiob = HILTCPPeripheral("GPIOB", 0x40020400, 0x400, port=5003)

        assert await gpioa.connect()
        assert await gpiob.connect()

        # Read from both
        moder_a = await gpioa.read(0x40020000, 4)
        moder_b = await gpiob.read(0x40020400, 4)

        print(f"GPIOA MODER = 0x{moder_a:08X}")
        print(f"GPIOB MODER = 0x{moder_b:08X}")

        assert moder_a == 0xA8000000
        assert moder_b == 0x00000280

        # Write to both
        await gpioa.write(0x40020014, 4, 0xAA)
        await gpiob.write(0x40020414, 4, 0x55)

        # Read back
        odr_a = await gpioa.read(0x40020014, 4)
        odr_b = await gpiob.read(0x40020414, 4)

        print(f"GPIOA ODR = 0x{odr_a:08X}")
        print(f"GPIOB ODR = 0x{odr_b:08X}")

        assert odr_a == 0xAA
        assert odr_b == 0x55

        await gpioa.disconnect()
        await gpiob.disconnect()
        print("PASS: Multiple peripherals test")
        return True

    except AssertionError as e:
        print(f"FAIL: {e}")
        return False
    finally:
        await mock_hw.stop()


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Run all HIL tests."""
    print("=" * 60)
    print("MCUemu Hardware-in-the-Loop (HIL) Tests")
    print("=" * 60)

    results = []
    results.append(await test_basic_read_write())
    results.append(await test_bsrr_operation())
    results.append(await test_multiple_peripherals())

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("All HIL tests PASSED!")
        return 0
    else:
        print("Some tests FAILED!")
        return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
