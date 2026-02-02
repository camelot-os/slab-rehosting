#!/usr/bin/env python3
"""
MCU Hardware Comparison Benchmark

Compares emulation performance against real hardware specifications
from official datasheets and reference manuals.

Data sources:
- STM32F439: RM0090, DS10314 (STMicroelectronics)
- STM32L476: RM0351, DS10198 (STMicroelectronics)
- NRF52840: PS v1.7 (Nordic Semiconductor)
- RP2040: Datasheet (Raspberry Pi)
- RP2350: Datasheet (Raspberry Pi)
- LPC55S69: UM11126, DS13773 (NXP)
- i.MX RT1060: IMXRT1060RM (NXP)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os
import time
import statistics
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'python'))


@dataclass
class HardwareSpecs:
    """Real hardware specifications from datasheets."""
    mcu_name: str
    vendor: str
    part_number: str
    datasheet_ref: str

    # CPU
    cpu_core: str
    cpu_freq_mhz: int
    cpu_dmips: float  # Dhrystone MIPS

    # Bus speeds
    ahb_freq_mhz: int
    apb1_freq_mhz: int
    apb2_freq_mhz: int

    # Memory
    flash_kb: int
    sram_kb: int
    flash_wait_states: int

    # Peripheral speeds (max)
    i2c_max_khz: int      # Standard/Fast/Fast+ mode
    spi_max_mhz: float
    uart_max_mbps: float

    # DMA
    dma_channels: int
    dma_max_mbps: float   # Theoretical max throughput

    # Crypto (if available)
    aes_throughput_mbps: float = 0
    sha_throughput_mbps: float = 0
    rng_throughput_kbps: float = 0

    # Special features
    features: str = ""


# Real hardware specifications from datasheets
HARDWARE_SPECS = {
    "STM32F439": HardwareSpecs(
        mcu_name="STM32F439",
        vendor="STMicroelectronics",
        part_number="STM32F439ZIT6",
        datasheet_ref="RM0090 Rev 19, DS10314 Rev 9",
        cpu_core="Cortex-M4F",
        cpu_freq_mhz=180,
        cpu_dmips=225,  # 1.25 DMIPS/MHz * 180MHz
        ahb_freq_mhz=180,
        apb1_freq_mhz=45,
        apb2_freq_mhz=90,
        flash_kb=2048,
        sram_kb=256,
        flash_wait_states=5,  # At 180MHz, 3.3V
        i2c_max_khz=400,      # Fast mode
        spi_max_mhz=45,       # APB2/2
        uart_max_mbps=5.625,  # 45MHz/8
        dma_channels=16,      # 2 DMA controllers x 8 streams
        dma_max_mbps=180,     # AHB speed
        aes_throughput_mbps=139,  # AES-128 ECB from datasheet
        sha_throughput_mbps=139,  # SHA-1 from datasheet
        rng_throughput_kbps=40,   # 40 kbps
        features="CRYP, HASH, RNG, DCMI, Ethernet, USB OTG HS/FS, FSMC"
    ),

    "STM32L476": HardwareSpecs(
        mcu_name="STM32L476",
        vendor="STMicroelectronics",
        part_number="STM32L476RGT6",
        datasheet_ref="RM0351 Rev 9, DS10198 Rev 7",
        cpu_core="Cortex-M4F",
        cpu_freq_mhz=80,
        cpu_dmips=100,  # 1.25 DMIPS/MHz * 80MHz
        ahb_freq_mhz=80,
        apb1_freq_mhz=80,
        apb2_freq_mhz=80,
        flash_kb=1024,
        sram_kb=128,
        flash_wait_states=4,  # At 80MHz
        i2c_max_khz=1000,     # Fast mode plus
        spi_max_mhz=40,       # APB/2
        uart_max_mbps=10,     # 80MHz/8
        dma_channels=14,      # 2 DMA x 7 channels
        dma_max_mbps=80,
        aes_throughput_mbps=25,  # AES-256 @ 80MHz
        sha_throughput_mbps=0,
        rng_throughput_kbps=40,
        features="AES-256, DFSDM, LCD, USB, Low Power"
    ),

    "NRF52840": HardwareSpecs(
        mcu_name="NRF52840",
        vendor="Nordic Semiconductor",
        part_number="NRF52840-QIAA",
        datasheet_ref="PS v1.7",
        cpu_core="Cortex-M4F",
        cpu_freq_mhz=64,
        cpu_dmips=80,  # 1.25 DMIPS/MHz * 64MHz
        ahb_freq_mhz=64,
        apb1_freq_mhz=64,
        apb2_freq_mhz=64,
        flash_kb=1024,
        sram_kb=256,
        flash_wait_states=0,  # With cache
        i2c_max_khz=400,      # Fast mode (TWIM)
        spi_max_mhz=32,       # SPIM max
        uart_max_mbps=1,      # 1 Mbps UARTE
        dma_channels=8,       # EasyDMA per peripheral
        dma_max_mbps=64,
        aes_throughput_mbps=16,   # CCM/ECB at 64MHz
        sha_throughput_mbps=0,
        rng_throughput_kbps=4000, # 4 Mbps (fast!)
        features="BLE 5.0, 802.15.4, Thread, Zigbee, USB, QSPI, NFC"
    ),

    "RP2040": HardwareSpecs(
        mcu_name="RP2040",
        vendor="Raspberry Pi",
        part_number="RP2040",
        datasheet_ref="RP2040 Datasheet",
        cpu_core="Dual Cortex-M0+",
        cpu_freq_mhz=133,
        cpu_dmips=133,  # 1.0 DMIPS/MHz * 133MHz (per core)
        ahb_freq_mhz=133,
        apb1_freq_mhz=133,
        apb2_freq_mhz=133,
        flash_kb=0,       # External via QSPI
        sram_kb=264,
        flash_wait_states=0,
        i2c_max_khz=1000,     # Fast mode plus
        spi_max_mhz=62.5,     # CLK/2
        uart_max_mbps=7.8,    # 133/16
        dma_channels=12,
        dma_max_mbps=133,
        aes_throughput_mbps=0,
        sha_throughput_mbps=0,
        rng_throughput_kbps=0,
        features="Dual-core, 8 PIO state machines, USB 1.1"
    ),

    "RP2350": HardwareSpecs(
        mcu_name="RP2350",
        vendor="Raspberry Pi",
        part_number="RP2350",
        datasheet_ref="RP2350 Datasheet",
        cpu_core="Dual Cortex-M33 / RISC-V",
        cpu_freq_mhz=150,
        cpu_dmips=225,  # 1.5 DMIPS/MHz * 150MHz (M33)
        ahb_freq_mhz=150,
        apb1_freq_mhz=150,
        apb2_freq_mhz=150,
        flash_kb=0,       # External
        sram_kb=520,
        flash_wait_states=0,
        i2c_max_khz=1000,
        spi_max_mhz=75,
        uart_max_mbps=9.375,
        dma_channels=16,
        dma_max_mbps=150,
        aes_throughput_mbps=0,   # No AES
        sha_throughput_mbps=150, # SHA-256 accelerator
        rng_throughput_kbps=48,  # TRNG
        features="TrustZone, SHA-256, TRNG, OTP, Glitch Detector, 12 PIO"
    ),

    "LPC55S69": HardwareSpecs(
        mcu_name="LPC55S69",
        vendor="NXP",
        part_number="LPC55S69JBD100",
        datasheet_ref="UM11126 Rev 2.4, DS13773",
        cpu_core="Dual Cortex-M33",
        cpu_freq_mhz=150,
        cpu_dmips=225,  # 1.5 DMIPS/MHz * 150MHz
        ahb_freq_mhz=150,
        apb1_freq_mhz=150,
        apb2_freq_mhz=150,
        flash_kb=640,
        sram_kb=320,
        flash_wait_states=8,  # At 150MHz
        i2c_max_khz=1000,     # Fast mode plus
        spi_max_mhz=50,       # High-speed SPI
        uart_max_mbps=9.375,
        dma_channels=23,
        dma_max_mbps=150,
        aes_throughput_mbps=96,    # HASHCRYPT AES
        sha_throughput_mbps=80,    # HASHCRYPT SHA-256
        rng_throughput_kbps=128,
        features="TrustZone, CASPER PKC, PUF, FlexComm, USB HS, SD/MMC"
    ),

    "IMXRT1060": HardwareSpecs(
        mcu_name="i.MX RT1060",
        vendor="NXP",
        part_number="MIMXRT1062DVL6A",
        datasheet_ref="IMXRT1060RM Rev 3",
        cpu_core="Cortex-M7",
        cpu_freq_mhz=600,
        cpu_dmips=1500,  # 2.5 DMIPS/MHz * 600MHz (with cache)
        ahb_freq_mhz=600,
        apb1_freq_mhz=150,
        apb2_freq_mhz=150,
        flash_kb=0,       # External
        sram_kb=1024,
        flash_wait_states=0,  # With cache/TCM
        i2c_max_khz=1000,     # LPI2C
        spi_max_mhz=60,       # LPSPI
        uart_max_mbps=9.375,  # LPUART
        dma_channels=32,      # eDMA
        dma_max_mbps=600,
        aes_throughput_mbps=0,   # DCP for basic crypto
        sha_throughput_mbps=0,
        rng_throughput_kbps=0,
        features="600MHz Cortex-M7, FlexRAM, FlexCAN FD, USB HS, LCD, CSI"
    ),
}


@dataclass
class PerformanceComparison:
    """Comparison between emulation and hardware."""
    metric: str
    unit: str
    hardware_value: float
    emulated_value: float
    ratio: float  # emulated/hardware
    efficiency_pct: float


@dataclass
class MCUComparisonReport:
    """Full comparison report for an MCU."""
    mcu_name: str
    hardware_specs: HardwareSpecs
    emulation_init_ms: float
    comparisons: List[PerformanceComparison] = field(default_factory=list)
    notes: str = ""


class HardwareComparisonBenchmark:
    """Benchmark comparing emulation to real hardware specs."""

    def __init__(self, iterations: int = 1000):
        self.iterations = iterations
        self.reports: List[MCUComparisonReport] = []

    def measure_operation(self, operation, iterations: int = None) -> float:
        """Measure operation speed in ops/sec."""
        if iterations is None:
            iterations = self.iterations

        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            operation()
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_time = statistics.mean(times)
        return 1.0 / avg_time if avg_time > 0 else 0

    def benchmark_stm32f439(self) -> MCUComparisonReport:
        """Benchmark STM32F439 against datasheet specs."""
        from slab_stm32 import STM32F439PeripheralSet

        hw = HARDWARE_SPECS["STM32F439"]

        start = time.perf_counter()
        stm32 = STM32F439PeripheralSet()
        init_time = (time.perf_counter() - start) * 1000

        report = MCUComparisonReport(
            mcu_name="STM32F439",
            hardware_specs=hw,
            emulation_init_ms=init_time
        )

        # I2C throughput comparison
        # Real hardware: 400 kHz * 8 bits = 3.2 Mbps max (Fast mode)
        # But with overhead, practical is ~300 kbps for byte transfers
        i2c = stm32.i2c1
        i2c_ops = self.measure_operation(lambda: i2c.read(0x10, 4))
        hw_i2c_ops = hw.i2c_max_khz * 1000 / 9  # 9 bits per byte with ACK

        report.comparisons.append(PerformanceComparison(
            metric="I2C Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_i2c_ops,
            emulated_value=i2c_ops,
            ratio=i2c_ops / hw_i2c_ops if hw_i2c_ops > 0 else 0,
            efficiency_pct=(i2c_ops / hw_i2c_ops * 100) if hw_i2c_ops > 0 else 0
        ))

        # SPI throughput comparison
        # Real hardware: 45 MHz / 8 bits = 5.625 MB/s theoretical
        spi = stm32.spi1
        spi_ops = self.measure_operation(lambda: spi.read(0x00, 4))
        hw_spi_ops = hw.spi_max_mhz * 1_000_000 / 8  # bytes/sec

        report.comparisons.append(PerformanceComparison(
            metric="SPI Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_spi_ops,
            emulated_value=spi_ops,
            ratio=spi_ops / hw_spi_ops if hw_spi_ops > 0 else 0,
            efficiency_pct=(spi_ops / hw_spi_ops * 100) if hw_spi_ops > 0 else 0
        ))

        # DMA throughput
        dma = stm32.dma2
        dma_ops = self.measure_operation(lambda: dma.read(0x00, 4))
        hw_dma_ops = hw.dma_max_mbps * 1_000_000 / 4  # 32-bit words/sec

        report.comparisons.append(PerformanceComparison(
            metric="DMA Register Access",
            unit="words/sec",
            hardware_value=hw_dma_ops,
            emulated_value=dma_ops,
            ratio=dma_ops / hw_dma_ops if hw_dma_ops > 0 else 0,
            efficiency_pct=(dma_ops / hw_dma_ops * 100) if hw_dma_ops > 0 else 0
        ))

        # CPU DMIPS comparison (register ops as proxy)
        reg_ops = self.measure_operation(lambda: i2c.read(0x00, 4))
        # Assume ~10 cycles per register operation on real hardware
        hw_reg_ops = hw.cpu_freq_mhz * 1_000_000 / 10

        report.comparisons.append(PerformanceComparison(
            metric="Register Operations",
            unit="ops/sec",
            hardware_value=hw_reg_ops,
            emulated_value=reg_ops,
            ratio=reg_ops / hw_reg_ops if hw_reg_ops > 0 else 0,
            efficiency_pct=(reg_ops / hw_reg_ops * 100) if hw_reg_ops > 0 else 0
        ))

        return report

    def benchmark_nrf52840(self) -> MCUComparisonReport:
        """Benchmark NRF52840 against datasheet specs."""
        from slab_nrf import NRF52840PeripheralSet

        hw = HARDWARE_SPECS["NRF52840"]

        start = time.perf_counter()
        nrf = NRF52840PeripheralSet()
        init_time = (time.perf_counter() - start) * 1000

        report = MCUComparisonReport(
            mcu_name="NRF52840",
            hardware_specs=hw,
            emulation_init_ms=init_time
        )

        # TWIM (I2C) throughput
        twim = nrf.twim0
        twim_ops = self.measure_operation(lambda: twim.read(0x00, 4))
        hw_twim_ops = hw.i2c_max_khz * 1000 / 9

        report.comparisons.append(PerformanceComparison(
            metric="TWIM Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_twim_ops,
            emulated_value=twim_ops,
            ratio=twim_ops / hw_twim_ops if hw_twim_ops > 0 else 0,
            efficiency_pct=(twim_ops / hw_twim_ops * 100) if hw_twim_ops > 0 else 0
        ))

        # SPIM throughput
        spim = nrf.spim0
        spim_ops = self.measure_operation(lambda: spim.read(0x00, 4))
        hw_spim_ops = hw.spi_max_mhz * 1_000_000 / 8

        report.comparisons.append(PerformanceComparison(
            metric="SPIM Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_spim_ops,
            emulated_value=spim_ops,
            ratio=spim_ops / hw_spim_ops if hw_spim_ops > 0 else 0,
            efficiency_pct=(spim_ops / hw_spim_ops * 100) if hw_spim_ops > 0 else 0
        ))

        # QSPI throughput (4x SPI speed)
        qspi = nrf.qspi
        qspi_ops = self.measure_operation(lambda: qspi.read(0x00, 4))
        hw_qspi_ops = hw.spi_max_mhz * 4 * 1_000_000 / 8  # Quad mode

        report.comparisons.append(PerformanceComparison(
            metric="QSPI Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_qspi_ops,
            emulated_value=qspi_ops,
            ratio=qspi_ops / hw_qspi_ops if hw_qspi_ops > 0 else 0,
            efficiency_pct=(qspi_ops / hw_qspi_ops * 100) if hw_qspi_ops > 0 else 0
        ))

        return report

    def benchmark_rp2040(self) -> MCUComparisonReport:
        """Benchmark RP2040 against datasheet specs."""
        from slab_rp2040 import RP2040PeripheralSet

        hw = HARDWARE_SPECS["RP2040"]

        start = time.perf_counter()
        rp = RP2040PeripheralSet()
        init_time = (time.perf_counter() - start) * 1000

        report = MCUComparisonReport(
            mcu_name="RP2040",
            hardware_specs=hw,
            emulation_init_ms=init_time
        )

        # I2C throughput
        i2c = rp.i2c0
        i2c_ops = self.measure_operation(lambda: i2c.read(0x00, 4))
        hw_i2c_ops = hw.i2c_max_khz * 1000 / 9

        report.comparisons.append(PerformanceComparison(
            metric="I2C Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_i2c_ops,
            emulated_value=i2c_ops,
            ratio=i2c_ops / hw_i2c_ops if hw_i2c_ops > 0 else 0,
            efficiency_pct=(i2c_ops / hw_i2c_ops * 100) if hw_i2c_ops > 0 else 0
        ))

        # SPI throughput
        spi = rp.spi0
        spi_ops = self.measure_operation(lambda: spi.read(0x00, 4))
        hw_spi_ops = hw.spi_max_mhz * 1_000_000 / 8

        report.comparisons.append(PerformanceComparison(
            metric="SPI Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_spi_ops,
            emulated_value=spi_ops,
            ratio=spi_ops / hw_spi_ops if hw_spi_ops > 0 else 0,
            efficiency_pct=(spi_ops / hw_spi_ops * 100) if hw_spi_ops > 0 else 0
        ))

        return report

    def benchmark_rp2350(self) -> MCUComparisonReport:
        """Benchmark RP2350 against datasheet specs."""
        from slab_rp2040 import RP2350PeripheralSet

        hw = HARDWARE_SPECS["RP2350"]

        start = time.perf_counter()
        rp = RP2350PeripheralSet()
        init_time = (time.perf_counter() - start) * 1000

        report = MCUComparisonReport(
            mcu_name="RP2350",
            hardware_specs=hw,
            emulation_init_ms=init_time
        )

        # SHA-256 throughput
        sha = rp.sha256
        sha_ops = self.measure_operation(lambda: sha.read(0x00, 4), iterations=500)
        # Real SHA-256: ~150 MB/s with hardware accelerator
        hw_sha_ops = hw.sha_throughput_mbps * 1_000_000  # bytes/sec

        report.comparisons.append(PerformanceComparison(
            metric="SHA-256 Register Access",
            unit="ops/sec",
            hardware_value=hw_sha_ops / 64,  # blocks/sec
            emulated_value=sha_ops,
            ratio=sha_ops / (hw_sha_ops / 64) if hw_sha_ops > 0 else 0,
            efficiency_pct=(sha_ops / (hw_sha_ops / 64) * 100) if hw_sha_ops > 0 else 0
        ))

        # TRNG throughput
        trng = rp.trng
        trng_ops = self.measure_operation(lambda: trng.read(0x00, 4))
        hw_trng_ops = hw.rng_throughput_kbps * 1000 / 8  # bytes/sec

        report.comparisons.append(PerformanceComparison(
            metric="TRNG Read",
            unit="bytes/sec",
            hardware_value=hw_trng_ops,
            emulated_value=trng_ops * 4,  # 4 bytes per read
            ratio=(trng_ops * 4) / hw_trng_ops if hw_trng_ops > 0 else 0,
            efficiency_pct=((trng_ops * 4) / hw_trng_ops * 100) if hw_trng_ops > 0 else 0
        ))

        return report

    def benchmark_lpc55s69(self) -> MCUComparisonReport:
        """Benchmark LPC55S69 against datasheet specs."""
        from slab_nxp import LPC55S69PeripheralSet

        hw = HARDWARE_SPECS["LPC55S69"]

        start = time.perf_counter()
        lpc = LPC55S69PeripheralSet()
        init_time = (time.perf_counter() - start) * 1000

        report = MCUComparisonReport(
            mcu_name="LPC55S69",
            hardware_specs=hw,
            emulation_init_ms=init_time
        )

        # FlexComm (SPI mode) throughput
        fc = lpc.flexcomm0
        fc_ops = self.measure_operation(lambda: fc.read(0x00, 4))
        hw_fc_ops = hw.spi_max_mhz * 1_000_000 / 8

        report.comparisons.append(PerformanceComparison(
            metric="FlexComm Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_fc_ops,
            emulated_value=fc_ops,
            ratio=fc_ops / hw_fc_ops if hw_fc_ops > 0 else 0,
            efficiency_pct=(fc_ops / hw_fc_ops * 100) if hw_fc_ops > 0 else 0
        ))

        # CASPER crypto
        casper = lpc.casper
        casper_ops = self.measure_operation(lambda: casper.read(0x00, 4))
        # CASPER can do RSA-2048 in ~1ms -> ~8000 ops/sec
        hw_casper_ops = 8000

        report.comparisons.append(PerformanceComparison(
            metric="CASPER Register Access",
            unit="ops/sec",
            hardware_value=hw_casper_ops,
            emulated_value=casper_ops,
            ratio=casper_ops / hw_casper_ops if hw_casper_ops > 0 else 0,
            efficiency_pct=(casper_ops / hw_casper_ops * 100) if hw_casper_ops > 0 else 0
        ))

        # HASHCRYPT
        hashcrypt = lpc.hashcrypt
        hash_ops = self.measure_operation(lambda: hashcrypt.read(0x00, 4))
        hw_hash_ops = hw.sha_throughput_mbps * 1_000_000 / 64  # blocks/sec

        report.comparisons.append(PerformanceComparison(
            metric="HASHCRYPT Register Access",
            unit="ops/sec",
            hardware_value=hw_hash_ops,
            emulated_value=hash_ops,
            ratio=hash_ops / hw_hash_ops if hw_hash_ops > 0 else 0,
            efficiency_pct=(hash_ops / hw_hash_ops * 100) if hw_hash_ops > 0 else 0
        ))

        return report

    def benchmark_imxrt1060(self) -> MCUComparisonReport:
        """Benchmark i.MX RT1060 against datasheet specs."""
        from slab_nxp import IMXRT1060PeripheralSet

        hw = HARDWARE_SPECS["IMXRT1060"]

        start = time.perf_counter()
        imxrt = IMXRT1060PeripheralSet()
        init_time = (time.perf_counter() - start) * 1000

        report = MCUComparisonReport(
            mcu_name="i.MX RT1060",
            hardware_specs=hw,
            emulation_init_ms=init_time
        )

        # LPI2C throughput
        lpi2c = imxrt.lpi2c1
        lpi2c_ops = self.measure_operation(lambda: lpi2c.read(0x00, 4))
        hw_lpi2c_ops = hw.i2c_max_khz * 1000 / 9

        report.comparisons.append(PerformanceComparison(
            metric="LPI2C Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_lpi2c_ops,
            emulated_value=lpi2c_ops,
            ratio=lpi2c_ops / hw_lpi2c_ops if hw_lpi2c_ops > 0 else 0,
            efficiency_pct=(lpi2c_ops / hw_lpi2c_ops * 100) if hw_lpi2c_ops > 0 else 0
        ))

        # LPSPI throughput
        lpspi = imxrt.lpspi1
        lpspi_ops = self.measure_operation(lambda: lpspi.read(0x00, 4))
        hw_lpspi_ops = hw.spi_max_mhz * 1_000_000 / 8

        report.comparisons.append(PerformanceComparison(
            metric="LPSPI Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_lpspi_ops,
            emulated_value=lpspi_ops,
            ratio=lpspi_ops / hw_lpspi_ops if hw_lpspi_ops > 0 else 0,
            efficiency_pct=(lpspi_ops / hw_lpspi_ops * 100) if hw_lpspi_ops > 0 else 0
        ))

        # LPUART throughput
        lpuart = imxrt.lpuart1
        lpuart_ops = self.measure_operation(lambda: lpuart.read(0x00, 4))
        hw_lpuart_ops = hw.uart_max_mbps * 1_000_000 / 10  # bytes/sec with overhead

        report.comparisons.append(PerformanceComparison(
            metric="LPUART Byte Transfer",
            unit="bytes/sec",
            hardware_value=hw_lpuart_ops,
            emulated_value=lpuart_ops,
            ratio=lpuart_ops / hw_lpuart_ops if hw_lpuart_ops > 0 else 0,
            efficiency_pct=(lpuart_ops / hw_lpuart_ops * 100) if hw_lpuart_ops > 0 else 0
        ))

        return report

    def run_all_benchmarks(self) -> List[MCUComparisonReport]:
        """Run all benchmarks."""
        benchmarks = [
            ("STM32F439", self.benchmark_stm32f439),
            ("NRF52840", self.benchmark_nrf52840),
            ("RP2040", self.benchmark_rp2040),
            ("RP2350", self.benchmark_rp2350),
            ("LPC55S69", self.benchmark_lpc55s69),
            ("i.MX RT1060", self.benchmark_imxrt1060),
        ]

        reports = []
        for name, func in benchmarks:
            print(f"Benchmarking {name}...", end=" ", flush=True)
            try:
                report = func()
                reports.append(report)
                print(f"OK")
            except Exception as e:
                print(f"FAILED: {e}")

        return reports

    def print_report(self, reports: List[MCUComparisonReport]):
        """Print comprehensive comparison report."""
        print("\n" + "=" * 100)
        print("MCU HARDWARE vs EMULATION COMPARISON REPORT")
        print("=" * 100)
        print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        # Hardware specifications table
        print("=" * 100)
        print("HARDWARE SPECIFICATIONS (from datasheets)")
        print("=" * 100)
        print(f"{'MCU':<15} {'Core':<20} {'Freq':>8} {'DMIPS':>8} {'Flash':>8} {'SRAM':>8} {'I2C':>8} {'SPI':>8}")
        print(f"{'':15} {'':20} {'(MHz)':>8} {'':>8} {'(KB)':>8} {'(KB)':>8} {'(kHz)':>8} {'(MHz)':>8}")
        print("-" * 100)

        for report in reports:
            hw = report.hardware_specs
            print(f"{hw.mcu_name:<15} {hw.cpu_core:<20} {hw.cpu_freq_mhz:>8} {hw.cpu_dmips:>8.0f} "
                  f"{hw.flash_kb:>8} {hw.sram_kb:>8} {hw.i2c_max_khz:>8} {hw.spi_max_mhz:>8.1f}")

        print()

        # Crypto capabilities
        print("=" * 100)
        print("CRYPTO & SECURITY CAPABILITIES")
        print("=" * 100)
        print(f"{'MCU':<15} {'AES':>12} {'SHA':>12} {'RNG':>12} {'Features'}")
        print(f"{'':15} {'(MB/s)':>12} {'(MB/s)':>12} {'(kbps)':>12} {''}")
        print("-" * 100)

        for report in reports:
            hw = report.hardware_specs
            aes = f"{hw.aes_throughput_mbps:.0f}" if hw.aes_throughput_mbps > 0 else "-"
            sha = f"{hw.sha_throughput_mbps:.0f}" if hw.sha_throughput_mbps > 0 else "-"
            rng = f"{hw.rng_throughput_kbps:.0f}" if hw.rng_throughput_kbps > 0 else "-"
            print(f"{hw.mcu_name:<15} {aes:>12} {sha:>12} {rng:>12} {hw.features[:45]}")

        print()

        # Emulation vs Hardware comparison
        print("=" * 100)
        print("EMULATION vs HARDWARE PERFORMANCE")
        print("=" * 100)

        for report in reports:
            hw = report.hardware_specs
            print(f"\n{'-' * 100}")
            print(f"MCU: {report.mcu_name} ({hw.cpu_core} @ {hw.cpu_freq_mhz}MHz)")
            print(f"Datasheet: {hw.datasheet_ref}")
            print(f"Emulation Init: {report.emulation_init_ms:.2f} ms")
            print(f"{'-' * 100}")
            print(f"{'Metric':<30} {'Hardware':>15} {'Emulated':>15} {'Ratio':>10} {'Note'}")
            print(f"{'-' * 100}")

            for comp in report.comparisons:
                hw_str = f"{comp.hardware_value:,.0f}"
                em_str = f"{comp.emulated_value:,.0f}"

                # Determine note based on ratio
                if comp.ratio > 100:
                    note = ">>> FASTER"
                elif comp.ratio > 10:
                    note = ">> faster"
                elif comp.ratio > 1:
                    note = "> faster"
                elif comp.ratio > 0.1:
                    note = "< slower"
                elif comp.ratio > 0.01:
                    note = "<< slower"
                else:
                    note = "<<< SLOWER"

                print(f"{comp.metric:<30} {hw_str:>15} {em_str:>15} {comp.ratio:>10.2f}x {note}")

        print()

        # Summary statistics
        print("=" * 100)
        print("SUMMARY: EMULATION SPEEDUP vs REAL HARDWARE")
        print("=" * 100)
        print(f"{'MCU':<20} {'Avg Speedup':>15} {'Min':>12} {'Max':>12} {'Interpretation'}")
        print("-" * 100)

        for report in reports:
            if report.comparisons:
                ratios = [c.ratio for c in report.comparisons if c.ratio > 0]
                if ratios:
                    avg = statistics.mean(ratios)
                    min_r = min(ratios)
                    max_r = max(ratios)

                    if avg > 10:
                        interp = "Emulation MUCH faster than HW"
                    elif avg > 1:
                        interp = "Emulation faster than HW"
                    elif avg > 0.5:
                        interp = "Comparable to HW"
                    else:
                        interp = "Emulation slower than HW"

                    print(f"{report.mcu_name:<20} {avg:>15.1f}x {min_r:>12.1f}x {max_r:>12.1f}x {interp}")

        print()
        print("=" * 100)
        print("NOTES:")
        print("- Hardware values are THEORETICAL MAXIMUMS from datasheets")
        print("- Emulation measures PYTHON register access overhead, not actual peripheral timing")
        print("- Ratios > 1.0 mean emulation processes registers faster than real hardware could")
        print("- This is expected since emulation skips actual signal propagation delays")
        print("- For functional testing, this speedup is beneficial")
        print("- For timing-accurate simulation, cycle-accurate mode would be needed")
        print("=" * 100)


def main():
    print("MCU Hardware Comparison Benchmark")
    print("Comparing emulation performance against datasheet specifications...\n")

    benchmark = HardwareComparisonBenchmark(iterations=1000)
    reports = benchmark.run_all_benchmarks()
    benchmark.print_report(reports)

    return 0


if __name__ == "__main__":
    sys.exit(main())
