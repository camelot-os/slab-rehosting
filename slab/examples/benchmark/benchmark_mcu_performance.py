#!/usr/bin/env python3
"""
MCU Performance Benchmark Suite

Measures performance metrics for each supported MCU family:
- Peripheral initialization time
- Register read/write throughput
- I2C/SPI transaction rates
- Memory operation speeds
- DMA transfer rates (where applicable)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os
import time
import statistics
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from contextlib import contextmanager

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'python'))


@dataclass
class BenchmarkResult:
    """Result of a single benchmark."""
    name: str
    iterations: int
    total_time_ms: float
    ops_per_second: float
    avg_time_us: float
    min_time_us: float
    max_time_us: float
    std_dev_us: float


@dataclass
class MCUPerformanceReport:
    """Performance report for a single MCU."""
    mcu_name: str
    architecture: str
    init_time_ms: float
    peripheral_count: int
    benchmarks: List[BenchmarkResult] = field(default_factory=list)
    memory_size: int = 0
    notes: str = ""


class PerformanceBenchmark:
    """Performance benchmark runner."""

    def __init__(self, iterations: int = 1000):
        self.iterations = iterations
        self.results: List[MCUPerformanceReport] = []

    @contextmanager
    def timer(self):
        """Context manager for timing operations."""
        start = time.perf_counter()
        yield
        self.elapsed = (time.perf_counter() - start) * 1000  # ms

    def benchmark_operation(self, name: str, operation: Callable, iterations: int = None) -> BenchmarkResult:
        """Benchmark a single operation."""
        if iterations is None:
            iterations = self.iterations

        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            operation()
            elapsed = (time.perf_counter() - start) * 1_000_000  # microseconds
            times.append(elapsed)

        total_time_ms = sum(times) / 1000
        ops_per_second = iterations / (total_time_ms / 1000) if total_time_ms > 0 else 0

        return BenchmarkResult(
            name=name,
            iterations=iterations,
            total_time_ms=total_time_ms,
            ops_per_second=ops_per_second,
            avg_time_us=statistics.mean(times),
            min_time_us=min(times),
            max_time_us=max(times),
            std_dev_us=statistics.stdev(times) if len(times) > 1 else 0
        )

    def benchmark_stm32f439(self) -> MCUPerformanceReport:
        """Benchmark STM32F439."""
        from slab_stm32 import STM32F439PeripheralSet
        from virtual_components import EEPROM_24Cxx, W25QxxFlash

        # Measure initialization time
        with self.timer():
            stm32 = STM32F439PeripheralSet()
        init_time = self.elapsed

        report = MCUPerformanceReport(
            mcu_name="STM32F439",
            architecture="Cortex-M4 @ 180MHz",
            init_time_ms=init_time,
            peripheral_count=len(stm32.peripherals) if hasattr(stm32, 'peripherals') else 8,
            notes="Hardware crypto (CRYP/HASH), FMC, USB OTG"
        )

        # Benchmark I2C register operations
        i2c = stm32.i2c1
        report.benchmarks.append(
            self.benchmark_operation("I2C Register Read", lambda: i2c.read(0x10, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("I2C Register Write", lambda: i2c.write(0x10, 4, 0x12345678))
        )

        # Benchmark SPI register operations
        spi = stm32.spi1
        report.benchmarks.append(
            self.benchmark_operation("SPI Register Read", lambda: spi.read(0x00, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("SPI Register Write", lambda: spi.write(0x00, 4, 0x0040))
        )

        # Benchmark DMA operations
        dma = stm32.dma2
        report.benchmarks.append(
            self.benchmark_operation("DMA Register Read", lambda: dma.read(0x00, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("DMA Register Write", lambda: dma.write(0x10, 4, 0x00000000))
        )

        # Benchmark with virtual EEPROM
        eeprom = EEPROM_24Cxx('24C256', address=0x50)

        # Setup I2C bridge for EEPROM
        write_buffer = bytearray()
        current_addr = [0]

        def i2c_on_start(addr, is_read):
            write_buffer.clear()

        def i2c_on_write(data):
            write_buffer.append(data)
            if len(write_buffer) == 2:
                current_addr[0] = (write_buffer[0] << 8) | write_buffer[1]

        def i2c_on_read():
            addr = current_addr[0]
            data = eeprom._memory[addr % eeprom.size]
            current_addr[0] = (addr + 1) % eeprom.size
            return data

        def i2c_on_stop():
            if len(write_buffer) > 2:
                start_addr = (write_buffer[0] << 8) | write_buffer[1]
                for i, byte in enumerate(write_buffer[2:]):
                    eeprom._memory[(start_addr + i) % eeprom.size] = byte

        i2c.on_start = i2c_on_start
        i2c.on_write = i2c_on_write
        i2c.on_read = i2c_on_read
        i2c.on_stop = i2c_on_stop

        # Benchmark EEPROM operations
        def eeprom_write_byte():
            i2c_on_start(0x50, False)
            i2c_on_write(0x00)
            i2c_on_write(0x00)
            i2c_on_write(0xAA)
            i2c_on_stop()

        def eeprom_read_byte():
            i2c_on_start(0x50, False)
            i2c_on_write(0x00)
            i2c_on_write(0x00)
            i2c_on_start(0x50, True)
            i2c_on_read()
            i2c_on_stop()

        report.benchmarks.append(
            self.benchmark_operation("EEPROM Write (1 byte)", eeprom_write_byte)
        )
        report.benchmarks.append(
            self.benchmark_operation("EEPROM Read (1 byte)", eeprom_read_byte)
        )

        # Benchmark SPI Flash operations
        flash = W25QxxFlash('W25Q128')

        def flash_read_jedec():
            return flash.JEDEC_IDS.get(flash.model, (0xEF, 0x40, 0x18))

        def flash_read_page():
            return bytes(flash._memory[0:256])

        report.benchmarks.append(
            self.benchmark_operation("Flash JEDEC ID Read", flash_read_jedec)
        )
        report.benchmarks.append(
            self.benchmark_operation("Flash Page Read (256B)", flash_read_page)
        )

        return report

    def benchmark_stm32l4xx(self) -> MCUPerformanceReport:
        """Benchmark STM32L4xx (L476)."""
        from slab_stm32 import STM32L476PeripheralSet
        from virtual_components import EEPROM_24Cxx

        with self.timer():
            stm32 = STM32L476PeripheralSet()
        init_time = self.elapsed

        report = MCUPerformanceReport(
            mcu_name="STM32L476",
            architecture="Cortex-M4 @ 80MHz",
            init_time_ms=init_time,
            peripheral_count=6,
            notes="Ultra-low-power, I2Cv2 architecture"
        )

        # Benchmark I2Cv2 operations
        i2c = stm32.i2c1
        report.benchmarks.append(
            self.benchmark_operation("I2Cv2 Register Read", lambda: i2c.read(0x00, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("I2Cv2 Register Write", lambda: i2c.write(0x00, 4, 0x00000000))
        )

        # Benchmark SPI operations
        spi = stm32.spi1
        report.benchmarks.append(
            self.benchmark_operation("SPI Register Read", lambda: spi.read(0x00, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("SPI Register Write", lambda: spi.write(0x00, 4, 0x00000000))
        )

        return report

    def benchmark_nrf52840(self) -> MCUPerformanceReport:
        """Benchmark NRF52840."""
        from slab_nrf import NRF52840PeripheralSet
        from virtual_components import EEPROM_24Cxx, W25QxxFlash

        with self.timer():
            nrf = NRF52840PeripheralSet()
        init_time = self.elapsed

        report = MCUPerformanceReport(
            mcu_name="NRF52840",
            architecture="Cortex-M4 @ 64MHz",
            init_time_ms=init_time,
            peripheral_count=10,
            notes="BLE 5.0, 802.15.4, USB, QSPI, Crypto"
        )

        # Benchmark TWIM (I2C) operations
        twim = nrf.twim0
        report.benchmarks.append(
            self.benchmark_operation("TWIM Register Read", lambda: twim.read(0x00, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("TWIM Register Write", lambda: twim.write(0x00, 4, 0x00000000))
        )

        # Benchmark SPIM operations
        spim = nrf.spim0
        report.benchmarks.append(
            self.benchmark_operation("SPIM Register Read", lambda: spim.read(0x00, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("SPIM Register Write", lambda: spim.write(0x00, 4, 0x00000000))
        )

        # Benchmark QSPI operations
        qspi = nrf.qspi
        report.benchmarks.append(
            self.benchmark_operation("QSPI Register Read", lambda: qspi.read(0x00, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("QSPI Register Write", lambda: qspi.write(0x500, 4, 0x00000001))
        )

        # Benchmark with virtual components
        eeprom = EEPROM_24Cxx('24C256', address=0x50)
        flash = W25QxxFlash('W25Q128')

        def flash_read_page():
            return bytes(flash._memory[0:256])

        report.benchmarks.append(
            self.benchmark_operation("Flash Page Read (256B)", flash_read_page)
        )

        return report

    def benchmark_rp2040(self) -> MCUPerformanceReport:
        """Benchmark RP2040."""
        from slab_rp2040 import RP2040PeripheralSet
        from virtual_components import EEPROM_24Cxx

        with self.timer():
            rp = RP2040PeripheralSet()
        init_time = self.elapsed

        report = MCUPerformanceReport(
            mcu_name="RP2040",
            architecture="Dual Cortex-M0+ @ 133MHz",
            init_time_ms=init_time,
            peripheral_count=8,
            notes="Dual-core, PIO state machines, USB"
        )

        # Benchmark I2C operations
        i2c = rp.i2c0
        report.benchmarks.append(
            self.benchmark_operation("I2C Register Read", lambda: i2c.read(0x00, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("I2C Register Write", lambda: i2c.write(0x00, 4, 0x00000000))
        )

        # Benchmark SPI operations
        spi = rp.spi0
        report.benchmarks.append(
            self.benchmark_operation("SPI Register Read", lambda: spi.read(0x00, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("SPI Register Write", lambda: spi.write(0x00, 4, 0x00000000))
        )

        return report

    def benchmark_rp2350(self) -> MCUPerformanceReport:
        """Benchmark RP2350."""
        from slab_rp2040 import RP2350PeripheralSet

        with self.timer():
            rp = RP2350PeripheralSet()
        init_time = self.elapsed

        report = MCUPerformanceReport(
            mcu_name="RP2350",
            architecture="Cortex-M33 @ 150MHz",
            init_time_ms=init_time,
            peripheral_count=12,
            notes="TrustZone, SHA256, TRNG, OTP, Glitch Detector"
        )

        # Benchmark I2C operations
        i2c = rp.i2c0
        report.benchmarks.append(
            self.benchmark_operation("I2C Register Read", lambda: i2c.read(0x00, 4))
        )

        # Benchmark security peripherals
        sha = rp.sha256
        report.benchmarks.append(
            self.benchmark_operation("SHA256 Register Read", lambda: sha.read(0x00, 4))
        )

        trng = rp.trng
        report.benchmarks.append(
            self.benchmark_operation("TRNG Register Read", lambda: trng.read(0x00, 4))
        )

        # Benchmark SHA256 hash operation
        def sha256_hash_block():
            # Simulate hashing 64 bytes
            sha.write(0x00, 4, 0x00000001)  # Start
            for i in range(16):
                sha.write(0x04, 4, 0x12345678)  # Data

        report.benchmarks.append(
            self.benchmark_operation("SHA256 Hash (64B block)", sha256_hash_block, iterations=500)
        )

        # Benchmark OTP read
        otp = rp.otp
        report.benchmarks.append(
            self.benchmark_operation("OTP Register Read", lambda: otp.read(0x00, 4))
        )

        return report

    def benchmark_lpc55s69(self) -> MCUPerformanceReport:
        """Benchmark LPC55S69."""
        from slab_nxp import LPC55S69PeripheralSet

        with self.timer():
            lpc = LPC55S69PeripheralSet()
        init_time = self.elapsed

        report = MCUPerformanceReport(
            mcu_name="LPC55S69",
            architecture="Cortex-M33 @ 150MHz",
            init_time_ms=init_time,
            peripheral_count=10,
            notes="TrustZone, CASPER crypto, PUF, FlexComm"
        )

        # Benchmark FlexComm operations
        fc0 = lpc.flexcomm0
        report.benchmarks.append(
            self.benchmark_operation("FlexComm Register Read", lambda: fc0.read(0x00, 4))
        )
        report.benchmarks.append(
            self.benchmark_operation("FlexComm Register Write", lambda: fc0.write(0x00, 4, 0x00000000))
        )

        # Benchmark CASPER crypto
        casper = lpc.casper
        report.benchmarks.append(
            self.benchmark_operation("CASPER Register Read", lambda: casper.read(0x00, 4))
        )

        # Benchmark HASHCRYPT
        hashcrypt = lpc.hashcrypt
        report.benchmarks.append(
            self.benchmark_operation("HASHCRYPT Register Read", lambda: hashcrypt.read(0x00, 4))
        )

        # Benchmark PUF
        puf = lpc.puf
        report.benchmarks.append(
            self.benchmark_operation("PUF Register Read", lambda: puf.read(0x00, 4))
        )

        return report

    def benchmark_imxrt1060(self) -> MCUPerformanceReport:
        """Benchmark i.MX RT1060."""
        from slab_nxp import IMXRT1060PeripheralSet

        with self.timer():
            imxrt = IMXRT1060PeripheralSet()
        init_time = self.elapsed

        report = MCUPerformanceReport(
            mcu_name="i.MX RT1060",
            architecture="Cortex-M7 @ 600MHz",
            init_time_ms=init_time,
            peripheral_count=8,
            notes="Crossover MCU, FlexCAN, USB, LCD"
        )

        # Benchmark LP peripherals
        lpuart = imxrt.lpuart1
        report.benchmarks.append(
            self.benchmark_operation("LPUART Register Read", lambda: lpuart.read(0x00, 4))
        )

        lpspi = imxrt.lpspi1
        report.benchmarks.append(
            self.benchmark_operation("LPSPI Register Read", lambda: lpspi.read(0x00, 4))
        )

        lpi2c = imxrt.lpi2c1
        report.benchmarks.append(
            self.benchmark_operation("LPI2C Register Read", lambda: lpi2c.read(0x00, 4))
        )

        return report

    def run_all_benchmarks(self) -> List[MCUPerformanceReport]:
        """Run benchmarks for all MCUs."""
        benchmarks = [
            ("STM32F439", self.benchmark_stm32f439),
            ("STM32L476", self.benchmark_stm32l4xx),
            ("NRF52840", self.benchmark_nrf52840),
            ("RP2040", self.benchmark_rp2040),
            ("RP2350", self.benchmark_rp2350),
            ("LPC55S69", self.benchmark_lpc55s69),
            ("i.MX RT1060", self.benchmark_imxrt1060),
        ]

        results = []
        for name, benchmark_func in benchmarks:
            print(f"\nBenchmarking {name}...", end=" ", flush=True)
            try:
                result = benchmark_func()
                results.append(result)
                print(f"OK ({result.init_time_ms:.2f}ms init)")
            except Exception as e:
                print(f"FAILED: {e}")

        return results

    def print_report(self, results: List[MCUPerformanceReport]):
        """Print performance report."""
        print("\n" + "=" * 80)
        print("MCU PERFORMANCE BENCHMARK REPORT")
        print("=" * 80)
        print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Iterations per benchmark: {self.iterations}")
        print()

        # Summary table
        print("-" * 80)
        print("MCU INITIALIZATION PERFORMANCE")
        print("-" * 80)
        print(f"{'MCU':<20} {'Architecture':<25} {'Init Time':<12} {'Peripherals'}")
        print("-" * 80)

        for r in sorted(results, key=lambda x: x.init_time_ms):
            print(f"{r.mcu_name:<20} {r.architecture:<25} {r.init_time_ms:>8.2f} ms  {r.peripheral_count:>3}")

        print()

        # Detailed benchmarks per MCU
        for report in results:
            print("=" * 80)
            print(f"MCU: {report.mcu_name}")
            print(f"Architecture: {report.architecture}")
            print(f"Initialization: {report.init_time_ms:.2f} ms")
            print(f"Notes: {report.notes}")
            print("-" * 80)
            print(f"{'Benchmark':<30} {'Ops/sec':>12} {'Avg (us)':>10} {'Min':>8} {'Max':>8} {'StdDev':>8}")
            print("-" * 80)

            for b in report.benchmarks:
                print(f"{b.name:<30} {b.ops_per_second:>12,.0f} {b.avg_time_us:>10.2f} "
                      f"{b.min_time_us:>8.2f} {b.max_time_us:>8.2f} {b.std_dev_us:>8.2f}")

            print()

        # Comparison table
        print("=" * 80)
        print("REGISTER ACCESS PERFORMANCE COMPARISON")
        print("=" * 80)
        print(f"{'MCU':<20} {'I2C Read':>15} {'SPI Read':>15} {'Write':>15}")
        print(f"{'':20} {'(ops/sec)':>15} {'(ops/sec)':>15} {'(ops/sec)':>15}")
        print("-" * 80)

        for report in results:
            i2c_read = next((b.ops_per_second for b in report.benchmarks
                           if 'I2C' in b.name and 'Read' in b.name), 0)
            spi_read = next((b.ops_per_second for b in report.benchmarks
                           if 'SPI' in b.name and 'Read' in b.name), 0)
            write = next((b.ops_per_second for b in report.benchmarks
                         if 'Write' in b.name), 0)

            print(f"{report.mcu_name:<20} {i2c_read:>15,.0f} {spi_read:>15,.0f} {write:>15,.0f}")

        print()

        # Performance ranking
        print("=" * 80)
        print("PERFORMANCE RANKING (by average register access speed)")
        print("=" * 80)

        rankings = []
        for report in results:
            avg_ops = statistics.mean([b.ops_per_second for b in report.benchmarks]) if report.benchmarks else 0
            rankings.append((report.mcu_name, avg_ops, report.architecture))

        for i, (name, ops, arch) in enumerate(sorted(rankings, key=lambda x: -x[1]), 1):
            print(f"  {i}. {name:<20} {ops:>12,.0f} ops/sec  ({arch})")

        print()
        print("=" * 80)


def main():
    """Run MCU performance benchmarks."""
    print("MCU Performance Benchmark Suite")
    print("Measuring peripheral emulation performance...")

    benchmark = PerformanceBenchmark(iterations=1000)
    results = benchmark.run_all_benchmarks()
    benchmark.print_report(results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
