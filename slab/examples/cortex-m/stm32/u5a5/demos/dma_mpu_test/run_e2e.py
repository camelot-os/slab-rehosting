#!/usr/bin/env python3
"""
Manual E2E runner for U5A5 DMA+MPU test.

Usage:
    PYTHONPATH=slab/python python3 slab/examples/cortex-m/stm32/u5a5/demos/dma_mpu_test/run_e2e.py

    # With GDB:
    PYTHONPATH=slab/python python3 slab/examples/cortex-m/stm32/u5a5/demos/dma_mpu_test/run_e2e.py --gdb

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
"""
import asyncio
import subprocess
import sys
import time
from pathlib import Path

# Resolve paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'slab' / 'python'))

from slab_cortex_m.board import BoardConfig, create_peripheral_set
from slab_cortex_m.base_server import BasePeripheralServer, STATUS_OK

QEMU_BIN = PROJECT_ROOT / 'build' / 'qemu-system-arm'
FIRMWARE_BIN = SCRIPT_DIR / 'build' / 'U5A5_DMA_MPU_Test.bin'
FIRMWARE_ELF = SCRIPT_DIR / 'build' / 'U5A5_DMA_MPU_Test.elf'


class DirectServer(BasePeripheralServer):
    """Server wrapping a PeripheralSet for direct MMIO proxying with IRQ."""

    def __init__(self, pset, port):
        super().__init__(port)
        self.pset = pset
        self.mmio_count = 0
        self.uart_output = bytearray()

        # Wire IRQ callbacks from all peripherals to send_irq
        if hasattr(pset, 'setup_irq_callback'):
            pset.setup_irq_callback(self.send_irq)

    def create_peripherals(self):
        pass

    def find_peripheral(self, addr):
        p = self.pset.find_peripheral(addr)
        if p is not None:
            self.mmio_count += 1
            return self
        return None

    def read(self, addr, size, secure=True):
        result = self.pset.read(addr, size)
        if isinstance(result, tuple):
            return result
        return (result if isinstance(result, int) else 0, STATUS_OK)

    def write(self, addr, size, value, secure=True):
        result = self.pset.write(addr, size, value)
        if isinstance(result, int):
            return result
        return STATUS_OK

    def contains(self, addr):
        return self.find_peripheral(addr) is not None


def uart_tx_handler(byte, buf):
    """Handle UART TX byte: capture and print to console."""
    b = byte & 0xFF
    buf.append(b)
    ch = chr(b) if 0x20 <= b < 0x7F or b in (0x0A, 0x0D) else '.'
    sys.stdout.write(ch)
    sys.stdout.flush()


async def main():
    use_gdb = '--gdb' in sys.argv
    port = 5555

    if not FIRMWARE_BIN.exists():
        print(f"Firmware not found: {FIRMWARE_BIN}")
        print("Run 'make' in the dma_mpu_test directory first.")
        return 1

    # Create peripheral set
    config = BoardConfig(name="U5A5_DMA_MPU_Test", mcu="STM32U5A5")
    pset = create_peripheral_set(config)

    server = DirectServer(pset, port)

    # Wire UART capture with real-time console output
    for p in getattr(pset, 'peripherals', []):
        pname = getattr(p, 'name', '')
        if ('USART' in pname or 'UART' in pname) and hasattr(p, 'on_tx'):
            buf = server.uart_output
            p.on_tx = lambda byte, b=buf: uart_tx_handler(byte, b)

    # Start TCP server
    server.running = True
    tcp_server = await asyncio.start_server(
        server.handle_client, '127.0.0.1', port, reuse_address=True)
    print(f"[server] Peripheral server listening on port {port}")
    print(f"[server] IRQ callback wired to {len(pset.peripherals)} peripherals")

    # Build QEMU command
    qemu_extra = {
        'sysclk-hz': '160000000',
        'sram-size': '0x270000',
        'flash-size': '0x400000',
        'periph-base': '0x0BFA0000',
        'periph-size': '0x54060000',
    }
    extra_props = ','.join(f'{k}={v}' for k, v in qemu_extra.items())
    machine_opts = f'slab-cortex-m,cpu-type=cortex-m33,tcp-port={port},{extra_props}'

    cmd = [
        str(QEMU_BIN),
        '-M', machine_opts,
        '-kernel', str(FIRMWARE_BIN),
        '-nographic', '-monitor', 'none',
    ]

    if use_gdb:
        cmd += ['-s', '-S']  # -s = gdbserver on :1234, -S = halt at start
        print(f"[qemu] Starting with GDB server on :1234 (halted)")
        print(f"[qemu] Connect with: arm-none-eabi-gdb {FIRMWARE_ELF}")
        print(f"[qemu]   (gdb) target remote :1234")
        print(f"[qemu]   (gdb) b main")
        print(f"[qemu]   (gdb) c")
    else:
        print(f"[qemu] Starting firmware execution...")

    print(f"[uart] --- USART1 output below ---")

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    timeout = 300 if use_gdb else 15

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.terminate()
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=3)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            stdout, stderr = b'', b''

    tcp_server.close()
    await tcp_server.wait_closed()

    # Results
    print(f"\n[uart] --- end ---")
    print(f"\n{'='*60}")
    print(f"  QEMU exit code: {proc.returncode}")
    print(f"  MMIO transactions: {server.mmio_count}")

    if stderr:
        stderr_str = stderr.decode('utf-8', errors='replace')
        err_lines = [l for l in stderr_str.strip().split('\n') if l.strip()]
        if err_lines:
            print(f"\n  QEMU stderr:")
            for line in err_lines[:10]:
                print(f"    {line.strip()}")

    # Verdict
    uart = server.uart_output.decode('ascii', errors='replace')
    print(f"\n{'='*60}")
    mpu_ok = 'MPU PMSAv8' in uart and 'regions OK' in uart
    dma_ok = 'DMA transfer complete' in uart
    all_ok = 'ALL TESTS PASSED' in uart

    if all_ok:
        print("  VERDICT: ALL TESTS PASSED")
        return 0
    elif mpu_ok and dma_ok:
        print("  VERDICT: DMA + MPU validated")
        return 0
    else:
        if not mpu_ok:
            print("  FAIL: MPU validation missing")
        if not dma_ok:
            print("  FAIL: DMA transfer not completed")
        return 1


if __name__ == '__main__':
    rc = asyncio.run(main())
    sys.exit(rc)
