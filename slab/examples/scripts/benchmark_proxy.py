#!/usr/bin/env python3
"""
TCP vs SHM Proxy Performance Benchmark

Compares latency and throughput of TCP and shared memory peripheral proxies.
Measures MMIO access performance critical for MCU firmware rehosting.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: GPL-2.0-or-later
"""

import os
import sys
import time
import signal
import socket
import struct
import subprocess
import threading
import statistics
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from multiprocessing import shared_memory

# Add Python packages to path
SLAB_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SLAB_ROOT / "python"))

QEMU_BIN = SLAB_ROOT.parent / "build" / "qemu-system-arm"


# =============================================================================
# TCP Peripheral Server (from run_all_rtos_tests.py)
# =============================================================================

@dataclass
class TCPPeripheralServer:
    """TCP-based peripheral server for benchmarking."""

    port: int = 5560

    # Peripheral registers
    regs: Dict[int, int] = field(default_factory=dict)

    # Peripheral bases
    RCC_BASE: int = 0x40023800
    TEST_BASE: int = 0x4000F000
    USART1_BASE: int = 0x40011000  # USART1 (Zephyr, NuttX)
    USART2_BASE: int = 0x40004400  # USART2 (HelloBlinkUart)
    TIM2_BASE: int = 0x40000000    # TIM2 for LED blink

    # State
    running: bool = False
    server_socket: Optional[socket.socket] = None
    client_socket: Optional[socket.socket] = None
    thread: Optional[threading.Thread] = None

    # Stats
    reads: int = 0
    writes: int = 0
    test_status: int = 0
    test_data: int = 0

    # Timing
    access_times: List[float] = field(default_factory=list)

    # Boot timing milestones (in seconds since server start)
    boot_start_time: float = 0.0      # When server started
    first_access_time: float = 0.0    # First MMIO access
    uart_ready_time: float = 0.0      # USART CR1 UE bit set
    uart_first_tx_time: float = 0.0   # First USART DR write

    def __post_init__(self):
        # RCC defaults
        self.regs[self.RCC_BASE + 0x00] = 0x00000083  # CR: HSIRDY
        self.regs[self.RCC_BASE + 0x74] = 0x00000000  # CSR

    def _handle_read(self, addr: int, size: int) -> int:
        """Handle read with RCC auto-ready."""
        self.reads += 1

        # Track first access
        if self.first_access_time == 0:
            self.first_access_time = time.perf_counter()

        # RCC CR - auto-set ready flags
        if addr == self.RCC_BASE:
            cr = self.regs.get(addr, 0x00000083)
            if cr & (1 << 16): cr |= (1 << 17)  # HSEON -> HSERDY
            if cr & (1 << 24): cr |= (1 << 25)  # PLLON -> PLLRDY
            return cr

        # RCC CSR - auto-set LSI ready
        if addr == self.RCC_BASE + 0x74:
            csr = self.regs.get(addr, 0)
            if csr & (1 << 0): csr |= (1 << 1)  # LSION -> LSIRDY
            return csr

        # RCC CFGR - auto-set SWS
        if addr == self.RCC_BASE + 0x08:
            cfgr = self.regs.get(addr, 0)
            sw = cfgr & 0x03
            return (cfgr & ~0x0C) | (sw << 2)

        # Test interface
        if addr == self.TEST_BASE:
            return self.test_status
        if addr == self.TEST_BASE + 0x04:
            return self.test_data

        # USART registers (STM32F4xx)
        # SR (0x00): TXE=bit7, TC=bit6, RXNE=bit5
        # DR (0x04): data register
        # BRR (0x08): baud rate
        # CR1 (0x0C): control
        for usart_base in (self.USART1_BASE, self.USART2_BASE):
            if addr == usart_base:  # SR
                return 0xC0  # TXE + TC always ready
            if addr == usart_base + 0x04:  # DR read
                return 0  # No data received
            if addr == usart_base + 0x0C:  # CR1
                return self.regs.get(addr, 0x2000)  # UE enabled

        # TIM2 registers (STM32F4xx)
        # SR (0x10): UIF=bit0 (update interrupt flag)
        if addr == self.TIM2_BASE + 0x10:  # SR
            return 0x01  # UIF set (trigger interrupt periodically)

        return self.regs.get(addr, 0)

    def _handle_write(self, addr: int, size: int, value: int):
        """Handle write."""
        self.writes += 1

        # Track first access
        if self.first_access_time == 0:
            self.first_access_time = time.perf_counter()

        self.regs[addr] = value

        if addr == self.TEST_BASE:
            self.test_status = value
        elif addr == self.TEST_BASE + 0x04:
            self.test_data = value

        # Track UART milestones (check both USART1 and USART2)
        for usart_base in (self.USART1_BASE, self.USART2_BASE):
            # CR1 (0x0C): UE bit (13) enables UART
            if addr == usart_base + 0x0C and (value & (1 << 13)):
                if self.uart_ready_time == 0:
                    self.uart_ready_time = time.perf_counter()

            # DR (0x04): First TX write
            if addr == usart_base + 0x04:
                if self.uart_first_tx_time == 0:
                    self.uart_first_tx_time = time.perf_counter()

    def _handle_packet(self, data: bytes) -> bytes:
        """Process packet - TCP protocol."""
        start = time.perf_counter()

        if len(data) < 10:
            return struct.pack('<IB', 0, 0)

        cmd = chr(data[0])
        addr = struct.unpack('<I', data[1:5])[0]
        size = struct.unpack('<I', data[5:9])[0]

        if cmd in ('R', 'S'):
            result = self._handle_read(addr, size)
            response = struct.pack('<IB', result, 0)
        elif cmd in ('W', 'T'):
            if len(data) >= 14:
                value = struct.unpack('<I', data[9:13])[0]
                self._handle_write(addr, size, value)
            response = struct.pack('<IB', 0, 0)
        else:
            response = struct.pack('<IB', 0, 1)

        elapsed = (time.perf_counter() - start) * 1_000_000  # microseconds
        self.access_times.append(elapsed)

        return response

    def _server_thread(self):
        """Server thread."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.server_socket.bind(('127.0.0.1', self.port))
        self.server_socket.listen(1)
        self.server_socket.settimeout(0.5)

        while self.running:
            try:
                client, _ = self.server_socket.accept()
                self.client_socket = client
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                client.settimeout(0.05)

                while self.running:
                    try:
                        first = client.recv(1, socket.MSG_PEEK)
                        if not first:
                            break
                        cmd = chr(first[0])
                        # Read=14B (cmd+addr+size+secure+PC), Write=18B (+value)
                        pkt_len = 14 if cmd in ('R', 'S') else 18
                        data = client.recv(pkt_len)
                        if not data:
                            break
                        response = self._handle_packet(data)
                        client.send(response)
                    except socket.timeout:
                        continue
                    except Exception:
                        break

                client.close()
                self.client_socket = None
            except socket.timeout:
                continue
            except Exception:
                break

        self.server_socket.close()

    def start(self):
        """Start server."""
        self.running = True
        self.boot_start_time = time.perf_counter()
        self.thread = threading.Thread(target=self._server_thread)
        self.thread.daemon = True
        self.thread.start()
        time.sleep(0.2)

    def stop(self):
        """Stop server."""
        self.running = False
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        if self.thread:
            self.thread.join(timeout=2)

    def get_latency_stats(self) -> Dict[str, float]:
        """Get latency statistics in microseconds."""
        if not self.access_times:
            return {}
        return {
            'min_us': min(self.access_times),
            'max_us': max(self.access_times),
            'avg_us': statistics.mean(self.access_times),
            'median_us': statistics.median(self.access_times),
            'stdev_us': statistics.stdev(self.access_times) if len(self.access_times) > 1 else 0,
            'p99_us': sorted(self.access_times)[int(len(self.access_times) * 0.99)] if self.access_times else 0,
        }

    def get_boot_timing(self) -> Dict[str, float]:
        """Get boot timing milestones in milliseconds."""
        t0 = self.boot_start_time
        return {
            'first_access_ms': (self.first_access_time - t0) * 1000 if self.first_access_time else 0,
            'uart_ready_ms': (self.uart_ready_time - t0) * 1000 if self.uart_ready_time else 0,
            'uart_first_tx_ms': (self.uart_first_tx_time - t0) * 1000 if self.uart_first_tx_time else 0,
        }


# =============================================================================
# SHM Peripheral Server
# =============================================================================

@dataclass
class ShmPeripheralServer:
    """Shared memory peripheral server for benchmarking."""

    shm_name: str = "slab_peripheral"
    region_size: int = 1024 * 1024  # 1MB

    # Peripheral registers
    regs: Dict[int, int] = field(default_factory=dict)

    # Peripheral bases
    RCC_BASE: int = 0x40023800
    TEST_BASE: int = 0x4000F000
    USART1_BASE: int = 0x40011000
    USART2_BASE: int = 0x40004400
    TIM2_BASE: int = 0x40000000

    # State
    running: bool = False
    shm: Optional[shared_memory.SharedMemory] = None
    thread: Optional[threading.Thread] = None

    # Stats
    reads: int = 0
    writes: int = 0
    test_status: int = 0
    test_data: int = 0

    # Timing
    access_times: List[float] = field(default_factory=list)

    # Boot timing milestones
    boot_start_time: float = 0.0
    first_access_time: float = 0.0
    uart_ready_time: float = 0.0
    uart_first_tx_time: float = 0.0

    # Protocol constants
    MAGIC: int = 0x534C4142  # "SLAB"
    HEADER_SIZE: int = 64

    def __post_init__(self):
        # RCC defaults
        self.regs[self.RCC_BASE + 0x00] = 0x00000083
        self.regs[self.RCC_BASE + 0x74] = 0x00000000

    def _handle_read(self, addr: int, size: int) -> int:
        """Handle read with RCC auto-ready."""
        self.reads += 1

        # Track first access
        if self.first_access_time == 0:
            self.first_access_time = time.perf_counter()

        if addr == self.RCC_BASE:
            cr = self.regs.get(addr, 0x00000083)
            if cr & (1 << 16): cr |= (1 << 17)
            if cr & (1 << 24): cr |= (1 << 25)
            return cr

        if addr == self.RCC_BASE + 0x74:
            csr = self.regs.get(addr, 0)
            if csr & (1 << 0): csr |= (1 << 1)
            return csr

        if addr == self.RCC_BASE + 0x08:
            cfgr = self.regs.get(addr, 0)
            sw = cfgr & 0x03
            return (cfgr & ~0x0C) | (sw << 2)

        if addr == self.TEST_BASE:
            return self.test_status
        if addr == self.TEST_BASE + 0x04:
            return self.test_data

        # USART registers
        for usart_base in (self.USART1_BASE, self.USART2_BASE):
            if addr == usart_base:  # SR
                return 0xC0  # TXE + TC always ready
            if addr == usart_base + 0x04:  # DR read
                return 0
            if addr == usart_base + 0x0C:  # CR1
                return self.regs.get(addr, 0x2000)

        # TIM2 registers
        if addr == self.TIM2_BASE + 0x10:  # SR
            return 0x01  # UIF set

        return self.regs.get(addr, 0)

    def _handle_write(self, addr: int, size: int, value: int):
        """Handle write."""
        self.writes += 1

        # Track first access
        if self.first_access_time == 0:
            self.first_access_time = time.perf_counter()

        self.regs[addr] = value

        if addr == self.TEST_BASE:
            self.test_status = value
        elif addr == self.TEST_BASE + 0x04:
            self.test_data = value

        # Track UART milestones (check both USART1 and USART2)
        for usart_base in (self.USART1_BASE, self.USART2_BASE):
            if addr == usart_base + 0x0C and (value & (1 << 13)):
                if self.uart_ready_time == 0:
                    self.uart_ready_time = time.perf_counter()

            if addr == usart_base + 0x04:
                if self.uart_first_tx_time == 0:
                    self.uart_first_tx_time = time.perf_counter()

    def _handler_loop(self):
        """
        Main handler loop - polls shared memory.

        QEMU SHM Protocol (v1, 32-bit):
          [0:4]   Magic (0x534C4142 = "SLAB")
          [4:8]   Version
          [8:12]  Command (from QEMU)
          [12:16] Status (from Python: 0=pending, 1=done)
          [16:20] Address (32-bit)
          [20:24] Data (32-bit)
          [24:28] Size
          [28:32] Sequence number
          [32:44] IRQ bitmap (3x32 = 96 IRQs)
        """
        last_seq = 0

        while self.running:
            # Read header (QEMU v1 protocol: 32-bit layout)
            header = bytes(self.shm.buf[:36])
            magic, version, command, status, address, data, size, seq = \
                struct.unpack('<IIIIIIII', header[:32])
            irq = struct.unpack('<I', header[32:36])[0]

            if magic != self.MAGIC:
                time.sleep(0.001)
                continue

            if seq != last_seq and command != 0:
                start = time.perf_counter()

                # Handle command (SHM_CMD_READ8=1, READ16=2, READ32=3, WRITE8=4, WRITE16=5, WRITE32=6)
                if command in (1, 2, 3):  # READ8/16/32
                    result = self._handle_read(address, size)
                elif command in (4, 5, 6):  # WRITE8/16/32
                    self._handle_write(address, size, data)
                    result = 0
                else:
                    result = 0

                # Write response (v1: 32-bit data at offset 20, status at offset 12)
                struct.pack_into('<I', self.shm.buf, 20, result & 0xFFFFFFFF)  # Data
                struct.pack_into('<I', self.shm.buf, 12, 1)  # Status = done

                elapsed = (time.perf_counter() - start) * 1_000_000
                self.access_times.append(elapsed)

                last_seq = seq
            # No sleep - tight polling for SHM performance

    def start(self):
        """Start server - create SHM region."""
        try:
            self.shm = shared_memory.SharedMemory(
                name=self.shm_name,
                create=True,
                size=self.region_size
            )
        except FileExistsError:
            # Clean up existing
            try:
                old = shared_memory.SharedMemory(name=self.shm_name)
                old.close()
                old.unlink()
            except:
                pass
            self.shm = shared_memory.SharedMemory(
                name=self.shm_name,
                create=True,
                size=self.region_size
            )

        # Initialize header (QEMU v1 protocol: 32-bit layout)
        # [0:4] magic, [4:8] version, [8:12] cmd, [12:16] status
        # [16:20] addr, [20:24] data, [24:28] size, [28:32] seq
        # [32:44] irq bitmap (3 words)
        header = struct.pack('<IIIIIIIIII',
            self.MAGIC, 1, 0, 0,  # magic, version=1, cmd=NOP, status=0
            0, 0, 0, 0,  # address, data, size, seq
            0, 0  # irq words 0-1 (word 2 follows)
        )
        for i, b in enumerate(header):
            self.shm.buf[i] = b
        # Clear rest of header
        for i in range(len(header), 64):
            self.shm.buf[i] = 0

        self.running = True
        self.boot_start_time = time.perf_counter()
        self.thread = threading.Thread(target=self._handler_loop, daemon=True)
        self.thread.start()
        time.sleep(0.2)

    def stop(self):
        """Stop server."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self.shm:
            self.shm.close()
            try:
                self.shm.unlink()
            except:
                pass

    def get_latency_stats(self) -> Dict[str, float]:
        """Get latency statistics in microseconds."""
        if not self.access_times:
            return {}
        return {
            'min_us': min(self.access_times),
            'max_us': max(self.access_times),
            'avg_us': statistics.mean(self.access_times),
            'median_us': statistics.median(self.access_times),
            'stdev_us': statistics.stdev(self.access_times) if len(self.access_times) > 1 else 0,
            'p99_us': sorted(self.access_times)[int(len(self.access_times) * 0.99)] if self.access_times else 0,
        }

    def get_boot_timing(self) -> Dict[str, float]:
        """Get boot timing milestones in milliseconds."""
        t0 = self.boot_start_time
        return {
            'first_access_ms': (self.first_access_time - t0) * 1000 if self.first_access_time else 0,
            'uart_ready_ms': (self.uart_ready_time - t0) * 1000 if self.uart_ready_time else 0,
            'uart_first_tx_ms': (self.uart_first_tx_time - t0) * 1000 if self.uart_first_tx_time else 0,
        }


# =============================================================================
# Benchmark Runner
# =============================================================================

def run_benchmark(firmware_path: Path, proxy_type: str, timeout: float = 5.0, quiet: bool = False) -> Dict:
    """
    Run firmware with specified proxy type and measure performance.

    Args:
        firmware_path: Path to firmware binary
        proxy_type: 'tcp' or 'shm'
        timeout: Test timeout in seconds
        quiet: Suppress output during benchmark

    Returns:
        Dict with results and latency stats
    """
    if not quiet:
        print(f"\n  Running {proxy_type.upper()} proxy benchmark...")

    if not firmware_path.exists():
        return {'status': 'skip', 'reason': 'Firmware not found'}

    if not QEMU_BIN.exists():
        return {'status': 'skip', 'reason': 'QEMU not found'}

    # Start appropriate server
    if proxy_type == 'tcp':
        server = TCPPeripheralServer(port=5560)
        server.start()
        qemu_args = [
            str(QEMU_BIN),
            "-M", "slab-cortex-m,tcp-port=5560",
            "-kernel", str(firmware_path),
            "-nographic",
        ]
    else:  # shm
        server = ShmPeripheralServer(shm_name="slab_benchmark")
        server.start()
        qemu_args = [
            str(QEMU_BIN),
            "-M", "slab-cortex-m,shm-name=/slab_benchmark",
            "-kernel", str(firmware_path),
            "-nographic",
        ]

    # Start QEMU (redirect to /dev/null in quiet mode for minimal I/O overhead)
    qemu_proc = subprocess.Popen(
        qemu_args,
        stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
        stderr=subprocess.DEVNULL if quiet else subprocess.PIPE,
        preexec_fn=os.setsid,
    )

    result = {'proxy': proxy_type, 'status': 'unknown'}
    start_time = time.time()

    try:
        while time.time() - start_time < timeout:
            time.sleep(0.1)

            if server.test_status == 2:  # PASS
                result['status'] = 'pass'
                break
            elif server.test_status == 3:  # FAIL
                result['status'] = 'fail'
                break

            if qemu_proc.poll() is not None:
                result['status'] = 'crash'
                break

        if result['status'] == 'unknown':
            if server.reads + server.writes > 0:
                result['status'] = 'timeout'
            else:
                result['status'] = 'no_activity'

        # Collect stats
        result['reads'] = server.reads
        result['writes'] = server.writes
        result['total_ops'] = server.reads + server.writes
        result['duration'] = time.time() - start_time
        result['ops_per_sec'] = result['total_ops'] / result['duration'] if result['duration'] > 0 else 0
        result['latency'] = server.get_latency_stats()
        result['boot_timing'] = server.get_boot_timing()

    except Exception as e:
        result['status'] = 'error'
        result['reason'] = str(e)

    finally:
        try:
            os.killpg(os.getpgid(qemu_proc.pid), signal.SIGTERM)
            qemu_proc.wait(timeout=2)
        except:
            try:
                qemu_proc.kill()
            except:
                pass
        server.stop()

    return result


def print_comparison(tcp_result: Dict, shm_result: Dict):
    """Print benchmark comparison table."""
    print("\n" + "=" * 80)
    print("  TCP vs SHM Proxy Performance Comparison")
    print("=" * 80)

    print(f"\n  {'Metric':<30} {'TCP':>20} {'SHM':>20} {'Speedup':>10}")
    print("  " + "-" * 78)

    # Status
    print(f"  {'Status':<30} {tcp_result.get('status', 'N/A'):>20} {shm_result.get('status', 'N/A'):>20}")

    # Operations
    tcp_ops = tcp_result.get('total_ops', 0)
    shm_ops = shm_result.get('total_ops', 0)
    print(f"  {'Total Operations':<30} {tcp_ops:>20} {shm_ops:>20}")

    tcp_reads = tcp_result.get('reads', 0)
    shm_reads = shm_result.get('reads', 0)
    print(f"  {'  Reads':<30} {tcp_reads:>20} {shm_reads:>20}")

    tcp_writes = tcp_result.get('writes', 0)
    shm_writes = shm_result.get('writes', 0)
    print(f"  {'  Writes':<30} {tcp_writes:>20} {shm_writes:>20}")

    # Throughput
    tcp_ops_sec = tcp_result.get('ops_per_sec', 0)
    shm_ops_sec = shm_result.get('ops_per_sec', 0)
    speedup_ops = shm_ops_sec / tcp_ops_sec if tcp_ops_sec > 0 else 0
    print(f"  {'Throughput (ops/sec)':<30} {tcp_ops_sec:>20.0f} {shm_ops_sec:>20.0f} {speedup_ops:>9.2f}x")

    # Latency
    print(f"\n  {'Latency (microseconds)':<30}")
    print("  " + "-" * 78)

    tcp_lat = tcp_result.get('latency', {})
    shm_lat = shm_result.get('latency', {})

    for metric in ['min_us', 'avg_us', 'median_us', 'p99_us', 'max_us']:
        tcp_val = tcp_lat.get(metric, 0)
        shm_val = shm_lat.get(metric, 0)
        speedup = tcp_val / shm_val if shm_val > 0 else 0
        label = metric.replace('_us', '').replace('_', ' ').title()
        print(f"  {'  ' + label:<30} {tcp_val:>20.2f} {shm_val:>20.2f} {speedup:>9.2f}x")

    print("  " + "-" * 78)

    # Boot timing
    tcp_boot = tcp_result.get('boot_timing', {})
    shm_boot = shm_result.get('boot_timing', {})

    if tcp_boot.get('first_access_ms') or shm_boot.get('first_access_ms'):
        print(f"\n  {'Boot Timing (milliseconds)':<30}")
        print("  " + "-" * 78)

        for metric in ['first_access_ms', 'uart_ready_ms', 'uart_first_tx_ms']:
            tcp_val = tcp_boot.get(metric, 0)
            shm_val = shm_boot.get(metric, 0)
            speedup = tcp_val / shm_val if shm_val > 0 else 0
            label = metric.replace('_ms', '').replace('_', ' ').title()
            print(f"  {'  ' + label:<30} {tcp_val:>20.2f} {shm_val:>20.2f} {speedup:>9.2f}x")

    # Summary
    avg_tcp = tcp_lat.get('avg_us', 0)
    avg_shm = shm_lat.get('avg_us', 0)
    if avg_shm > 0:
        latency_improvement = (avg_tcp - avg_shm) / avg_tcp * 100 if avg_tcp > 0 else 0
        print(f"\n  Average latency improvement: {latency_improvement:.1f}% (SHM is faster)")


def main():
    """Run TCP vs SHM proxy benchmark."""
    import argparse

    parser = argparse.ArgumentParser(
        description="TCP vs SHM Proxy Performance Benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This benchmark compares the performance of TCP and shared memory (SHM)
peripheral proxies for MCU firmware rehosting.

Metrics measured:
  - Throughput (MMIO operations per second)
  - Latency (min, avg, median, p99, max in microseconds)

Examples:
  %(prog)s                           # Benchmark default (HelloBlinkUart - UART, no USB)
  %(prog)s --firmware cubemx         # Benchmark CubeMX blinky
  %(prog)s --firmware helloblink     # Benchmark HelloBlink USB CDC (may have USB OTG polling)
  %(prog)s --timeout 10              # Run with longer timeout
"""
    )
    parser.add_argument('--firmware', type=str, default='helloblinkuart',
                        choices=['cubemx', 'freertos', 'helloblink', 'helloblinkuart', 'zephyr'],
                        help='Firmware to benchmark (helloblinkuart recommended for clean benchmarks)')
    parser.add_argument('--timeout', type=float, default=5.0,
                        help='Test timeout in seconds')
    parser.add_argument('--tcp-only', action='store_true',
                        help='Only run TCP benchmark')
    parser.add_argument('--shm-only', action='store_true',
                        help='Only run SHM benchmark')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Suppress output during benchmarks (cleaner measurements)')

    args = parser.parse_args()

    # Select firmware
    examples_dir = SLAB_ROOT / "examples"
    firmware_map = {
        'cubemx': examples_dir / 'cortex-m' / 'stm32' / 'f405' / 'rtos' / 'cubemx_blinky' / 'build' / 'blinky.bin',
        'freertos': examples_dir / 'cortex-m' / 'stm32' / 'f405' / 'rtos' / 'freertos_blinky' / 'build' / 'freertos_blinky.bin',
        'helloblink': examples_dir / 'cortex-m' / 'stm32' / 'f405' / 'demos' / 'hello_blink' / 'build' / 'HelloBlink.bin',
        'helloblinkuart': examples_dir / 'cortex-m' / 'stm32' / 'f405' / 'demos' / 'hello_blink_uart' / 'build' / 'HelloBlinkUart.bin',
        'zephyr': examples_dir / 'cortex-m' / 'stm32' / 'f407' / 'rtos' / 'zephyr_blinky' / 'build' / 'zephyr.bin',
    }
    firmware_path = firmware_map[args.firmware]

    print("=" * 80)
    print("  MCUemu Proxy Performance Benchmark")
    print("=" * 80)
    print(f"  Firmware: {firmware_path.name}")
    print(f"  Size: {firmware_path.stat().st_size if firmware_path.exists() else 'N/A'} bytes")
    print(f"  Timeout: {args.timeout}s")

    tcp_result = {}
    shm_result = {}

    # Run TCP benchmark
    if not args.shm_only:
        tcp_result = run_benchmark(firmware_path, 'tcp', args.timeout, args.quiet)
        if not args.quiet:
            print(f"    Status: {tcp_result.get('status')}")
            print(f"    Operations: {tcp_result.get('total_ops', 0)}")
            if tcp_result.get('latency'):
                print(f"    Avg Latency: {tcp_result['latency'].get('avg_us', 0):.2f} µs")

    # Run SHM benchmark
    if not args.tcp_only:
        shm_result = run_benchmark(firmware_path, 'shm', args.timeout, args.quiet)
        if not args.quiet:
            print(f"    Status: {shm_result.get('status')}")
            print(f"    Operations: {shm_result.get('total_ops', 0)}")
            if shm_result.get('latency'):
                print(f"    Avg Latency: {shm_result['latency'].get('avg_us', 0):.2f} µs")

    # Print comparison
    if tcp_result and shm_result:
        print_comparison(tcp_result, shm_result)

    print("\n" + "=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
