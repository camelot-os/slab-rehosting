#!/usr/bin/env python3
"""
SLAB Quickstart -- One-command firmware emulation from SVD

Given an SVD file and a firmware binary, this tool:
1. Parses the SVD to extract CPU type and memory layout
2. Generates a temporary board config with SVD auto-stub peripherals
3. Launches the SLAB peripheral server
4. (Optionally) launches QEMU and connects them

Usage:
    # Server only (connect your own QEMU):
    python3 -m slab.tools.quickstart --svd STM32F407.svd --port 5555

    # Full emulation (server + QEMU):
    python3 -m slab.tools.quickstart --svd STM32F407.svd \\
        --firmware build/app.bin --qemu build/qemu-system-arm

    # With binary patches:
    python3 -m slab.tools.quickstart --svd STM32F407.svd \\
        --firmware build/app.bin \\
        --patch 0x08001234:7047 \\
        --patch 0x08005678:00bf

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import argparse
import asyncio
import logging
import subprocess
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('Quickstart')


def parse_patch(patch_str: str):
    """Parse a patch string 'addr:hexdata' into (address, bytes)."""
    parts = patch_str.split(':', 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid patch format: {patch_str} (expected addr:hexdata)")
    addr = int(parts[0], 0)
    data = bytes.fromhex(parts[1].replace('0x', '').replace(' ', ''))
    return addr, data


def build_qemu_args(svd_info, firmware_path, port, qemu_path, extra_args=None):
    """Build QEMU command line from SVD memory info."""
    args = [
        qemu_path,
        '-M', 'slab-cortex-m,'
              f'cpu-type={svd_info["cpu_type"]},'
              f'flash-base={svd_info["flash_base"]},'
              f'flash-size={svd_info["flash_size"]},'
              f'sram-base={svd_info["sram_base"]},'
              f'sram-size={svd_info["sram_size"]},'
              f'periph-base={svd_info["periph_base"]},'
              f'periph-size={svd_info["periph_size"]},'
              f'tcp-port={port}',
        '-kernel', firmware_path,
        '-nographic',
    ]
    if extra_args:
        args.extend(extra_args)
    return args


async def run_server(svd_path, port, patches=None, firmware_path=None,
                     qemu_path=None, qemu_extra=None, memory_overrides=None,
                     verbose=False):
    """Run the SLAB peripheral server with SVD auto-stub peripherals."""
    from slab_cortex_m.svd_peripheral import SVDStubPeripheralSet
    from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
    from slab_cortex_m.base_server import BasePeripheralServer
    from slab_cortex_m.board import PatchEntry, BoardConfig, apply_patches

    # Create SVD stub peripheral set
    pset = SVDStubPeripheralSet.from_svd(svd_path)
    svd_info = pset.get_memory_info()

    # Apply memory overrides from CLI flags
    if memory_overrides:
        svd_info.update(memory_overrides)

    print(f"\n{'='*60}")
    print(f"  SLAB Quickstart")
    print(f"{'='*60}")
    print(f"  SVD:       {os.path.basename(svd_path)}")
    print(f"  Device:    {pset.name}")
    print(f"  CPU:       {svd_info['cpu_type']}")
    print(f"  Flash:     0x{svd_info['flash_base']:08X} ({svd_info['flash_size']//1024}KB)")
    print(f"  SRAM:      0x{svd_info['sram_base']:08X} ({svd_info['sram_size']//1024}KB)")
    print(f"  Periph:    0x{svd_info['periph_base']:08X} - "
          f"0x{svd_info['periph_base'] + svd_info['periph_size']:08X}")
    print(f"  Peripherals: {len(pset.peripherals)}")
    print(f"  Port:      {port}")

    # Apply patches to firmware if provided
    if firmware_path and patches:
        fw_data = bytearray(open(firmware_path, 'rb').read())
        config = BoardConfig(
            name="quickstart", mcu=f"SVD:{svd_path}",
            patches=[PatchEntry(addr, data) for addr, data in patches],
        )
        n = apply_patches(fw_data, config, load_base=svd_info['flash_base'])
        if n > 0:
            patched_path = firmware_path + '.patched'
            with open(patched_path, 'wb') as f:
                f.write(fw_data)
            firmware_path = patched_path
            print(f"  Patches:   {n} applied -> {patched_path}")

    print(f"{'='*60}\n")

    # Create adapter and server
    adapter = PeripheralSetAdapter(pset, family='stm32')

    class QuickstartServer(BasePeripheralServer):
        def __init__(self, port, adapter):
            super().__init__(port)
            self._adapter = adapter
            self._adapter.irq_callback = self.send_irq

        def create_peripherals(self):
            pass

        def find_peripheral(self, addr):
            if self._adapter.contains(addr):
                return self._adapter
            return None

    server = QuickstartServer(port, adapter)
    server.running = True

    tcp_server = await asyncio.start_server(
        server.handle_client, '127.0.0.1', port, reuse_address=True)

    print(f"[Server] Listening on tcp://127.0.0.1:{port}")

    tasks = [tcp_server.serve_forever()]

    # Launch QEMU if requested
    qemu_proc = None
    if firmware_path and qemu_path:
        qemu_args = build_qemu_args(
            svd_info, firmware_path, port, qemu_path, qemu_extra)
        print(f"[QEMU] {' '.join(qemu_args[:6])}...")
        qemu_proc = subprocess.Popen(
            qemu_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print(f"[QEMU] Started (PID {qemu_proc.pid})")
    elif firmware_path:
        # Print the QEMU command for the user
        qemu_cmd = build_qemu_args(
            svd_info, firmware_path, port,
            'build/qemu-system-arm')
        print(f"\n[QEMU] Run this in another terminal:")
        print(f"  {' '.join(qemu_cmd)}\n")

    try:
        await asyncio.gather(*tasks)
    finally:
        if qemu_proc:
            qemu_proc.terminate()
            qemu_proc.wait()


def main():
    parser = argparse.ArgumentParser(
        description='SLAB Quickstart - One-command firmware emulation from SVD',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
    # Server only (then launch QEMU separately):
    %(prog)s --svd STM32F407.svd --port 5555

    # Full emulation with QEMU:
    %(prog)s --svd STM32F407.svd --firmware app.bin --qemu build/qemu-system-arm

    # With binary patches (NOP a delay loop):
    %(prog)s --svd STM32F407.svd --firmware app.bin --patch 0x0800ABCD:7047

    # Override flash base for nRF:
    %(prog)s --svd nrf52840.svd --firmware app.bin --flash-base 0x00000000
''')

    parser.add_argument('--svd', required=True,
                        help='Path to SVD file')
    parser.add_argument('--firmware', '-f',
                        help='Path to firmware binary (.bin)')
    parser.add_argument('--port', '-p', type=int, default=5555,
                        help='TCP port (default: 5555)')
    parser.add_argument('--qemu', '-q',
                        help='Path to qemu-system-arm (launches QEMU automatically)')
    parser.add_argument('--patch', action='append', default=[],
                        help='Binary patch as addr:hexdata (repeatable)')
    parser.add_argument('--flash-base', type=lambda x: int(x, 0),
                        help='Override flash base address')
    parser.add_argument('--sram-base', type=lambda x: int(x, 0),
                        help='Override SRAM base address')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable debug logging')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Parse patches
    patches = []
    for p in args.patch:
        try:
            patches.append(parse_patch(p))
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Collect memory overrides
    overrides = {}
    if args.flash_base is not None:
        overrides['flash_base'] = args.flash_base
    if args.sram_base is not None:
        overrides['sram_base'] = args.sram_base

    try:
        asyncio.run(run_server(
            svd_path=args.svd,
            port=args.port,
            patches=patches,
            firmware_path=args.firmware,
            qemu_path=args.qemu,
            memory_overrides=overrides,
            verbose=args.verbose,
        ))
    except KeyboardInterrupt:
        print("\n[*] Shutdown")


if __name__ == '__main__':
    main()
