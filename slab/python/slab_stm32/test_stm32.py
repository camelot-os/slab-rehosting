#!/usr/bin/env python3
"""
STM32 Peripheral Test Suite

Comprehensive tests for STM32 peripheral emulation:
- GPIO (GPIOv1 and GPIOv2)
- RCC (Clock Control)
- USART (Serial Communication)
- SPI
- I2C
- DMA
- Timers
- ADC
- RNG
- Flash
- Watchdog

Run:
    python3 test_stm32.py

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import logging
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent))

from slab_stm32 import (
    # GPIO
    STM32GPIOv1, STM32GPIOv2, STM32EXTI,
    # RCC/System
    STM32RCCv2, STM32PWRv1, STM32FLASHv2, STM32SYSCFG,
    # Communication
    STM32USARTv1, STM32SPIv1, STM32I2Cv1,
    # Timers
    STM32BasicTimer, STM32GeneralTimer, STM32AdvancedTimer,
    # DMA
    STM32DMAv2,
    # Analog
    STM32ADCv2, STM32DAC,
    # Misc
    STM32RNG, STM32CRC, STM32IWDG, STM32WWDG,
    # Peripheral Sets
    STM32F407PeripheralSet,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('STM32.Test')


def test_gpio_v2_basic():
    """Test GPIOv2 (F4/L4/H7 style) basic operations."""
    print("\n" + "=" * 60)
    print("  Test 1: GPIOv2 Basic Operations")
    print("=" * 60 + "\n")

    gpio = STM32GPIOv2(port='A', base=0x40020000)

    # Default state: all pins analog (MODER = 0xFFFFFFFF for most)
    moder, _ = gpio.read(gpio.base + gpio.MODER, 4)
    print(f"  Default MODER: 0x{moder:08X}")

    # Configure PA5 as output (MODER bits [11:10] = 01)
    gpio.write(gpio.base + gpio.MODER, 4, 0x00000400)  # PA5 = output
    moder_after, _ = gpio.read(gpio.base + gpio.MODER, 4)
    print(f"  MODER after config PA5 output: 0x{moder_after:08X}")

    # Set PA5 high using ODR
    gpio.write(gpio.base + gpio.ODR, 4, 0x0020)
    odr, _ = gpio.read(gpio.base + gpio.ODR, 4)
    print(f"  ODR after set PA5: 0x{odr:04X}")

    # Set PA5 low using BSRR (high 16 bits = reset)
    gpio.write(gpio.base + gpio.BSRR, 4, 0x00200000)
    odr, _ = gpio.read(gpio.base + gpio.ODR, 4)
    print(f"  ODR after reset PA5: 0x{odr:04X}")

    # Set PA5 high using BSRR (low 16 bits = set)
    gpio.write(gpio.base + gpio.BSRR, 4, 0x00000020)
    odr, _ = gpio.read(gpio.base + gpio.ODR, 4)
    print(f"  ODR after set PA5 via BSRR: 0x{odr:04X}")

    # Verify IDR reflects output state
    idr, _ = gpio.read(gpio.base + gpio.IDR, 4)
    print(f"  IDR (input data): 0x{idr:04X}")

    pa5_set = (odr & 0x0020) != 0
    print(f"\n  PA5 state: {'HIGH' if pa5_set else 'LOW'}")
    print(f"\n  Result: {'PASS' if pa5_set else 'FAIL'}")
    return pa5_set


def test_gpio_v1_basic():
    """Test GPIOv1 (F1xx style) basic operations."""
    print("\n" + "=" * 60)
    print("  Test 2: GPIOv1 (F1xx) Basic Operations")
    print("=" * 60 + "\n")

    gpio = STM32GPIOv1(port='C', base=0x40011000)

    # Configure PC13 as output (CRH bits [23:20] = 0b0011 for 50MHz push-pull)
    # PC13 is in CRH (pins 8-15), position (13-8)*4 = 20
    gpio.write(gpio.base + gpio.CRH, 4, 0x00300000)
    crh, _ = gpio.read(gpio.base + gpio.CRH, 4)
    print(f"  CRH after config PC13 output: 0x{crh:08X}")

    # Toggle PC13 using BSRR
    gpio.write(gpio.base + gpio.BSRR, 4, 0x00002000)  # Set PC13
    odr, _ = gpio.read(gpio.base + gpio.ODR, 4)
    print(f"  ODR after set PC13: 0x{odr:04X}")

    gpio.write(gpio.base + gpio.BRR, 4, 0x00002000)  # Reset PC13
    odr, _ = gpio.read(gpio.base + gpio.ODR, 4)
    print(f"  ODR after reset PC13: 0x{odr:04X}")

    success = (crh == 0x00300000)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_rcc_clock_config():
    """Test RCC clock configuration."""
    print("\n" + "=" * 60)
    print("  Test 3: RCC Clock Configuration")
    print("=" * 60 + "\n")

    rcc = STM32RCCv2(base=0x40023800)

    # Read initial CR
    cr, _ = rcc.read(rcc.base + rcc.CR, 4)
    print(f"  Initial CR: 0x{cr:08X}")

    # Enable HSE
    rcc.write(rcc.base + rcc.CR, 4, cr | (1 << 16))  # HSEON
    cr, _ = rcc.read(rcc.base + rcc.CR, 4)
    hse_rdy = (cr >> 17) & 1
    print(f"  CR after HSEON: 0x{cr:08X} (HSERDY={hse_rdy})")

    # Configure PLL
    # PLLM=8, PLLN=336, PLLP=2, PLLQ=7, PLLSRC=HSE
    pllcfgr = (8 << 0) | (336 << 6) | (0 << 16) | (7 << 24) | (1 << 22)
    rcc.write(rcc.base + rcc.PLLCFGR, 4, pllcfgr)
    pllcfgr_read, _ = rcc.read(rcc.base + rcc.PLLCFGR, 4)
    print(f"  PLLCFGR: 0x{pllcfgr_read:08X}")

    # Enable PLL
    cr, _ = rcc.read(rcc.base + rcc.CR, 4)
    rcc.write(rcc.base + rcc.CR, 4, cr | (1 << 24))  # PLLON
    cr, _ = rcc.read(rcc.base + rcc.CR, 4)
    pll_rdy = (cr >> 25) & 1
    print(f"  CR after PLLON: 0x{cr:08X} (PLLRDY={pll_rdy})")

    # Enable GPIO clocks
    ahb1enr, _ = rcc.read(rcc.base + rcc.AHB1ENR, 4)
    rcc.write(rcc.base + rcc.AHB1ENR, 4, ahb1enr | 0x1FF)  # Enable GPIOA-I
    ahb1enr, _ = rcc.read(rcc.base + rcc.AHB1ENR, 4)
    print(f"  AHB1ENR (GPIO clocks): 0x{ahb1enr:08X}")

    success = (hse_rdy == 1 and pll_rdy == 1)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_usart_basic():
    """Test USART basic configuration and operation."""
    print("\n" + "=" * 60)
    print("  Test 4: USART Basic Operations")
    print("=" * 60 + "\n")

    usart = STM32USARTv1(index=1, base=0x40011000)

    # Configure 115200 baud (assuming 16MHz APB clock)
    # BRR = fck / baud = 16000000 / 115200 = 138.89 ≈ 139
    usart.write(usart.base + usart.BRR, 4, 139)
    brr, _ = usart.read(usart.base + usart.BRR, 4)
    print(f"  BRR = {brr} (baud rate divisor)")

    # Enable USART, TX, RX
    cr1 = (1 << 13) | (1 << 3) | (1 << 2)  # UE | TE | RE
    usart.write(usart.base + usart.CR1, 4, cr1)
    cr1_read, _ = usart.read(usart.base + usart.CR1, 4)
    print(f"  CR1 = 0x{cr1_read:08X} (UE|TE|RE enabled)")

    # Check status register
    sr, _ = usart.read(usart.base + usart.SR, 4)
    txe = (sr >> 7) & 1
    tc = (sr >> 6) & 1
    print(f"  SR = 0x{sr:08X} (TXE={txe}, TC={tc})")

    # Write data to transmit
    usart.write(usart.base + usart.DR, 4, ord('A'))
    dr, _ = usart.read(usart.base + usart.DR, 4)
    print(f"  DR after TX 'A': 0x{dr:02X}")

    # Check SR after TX (TXE should be set since TX buffer is empty again)
    sr_after, _ = usart.read(usart.base + usart.SR, 4)
    txe_after = (sr_after >> 7) & 1
    print(f"  SR after TX: 0x{sr_after:08X} (TXE={txe_after})")

    success = (cr1_read == cr1) and (txe_after == 1)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_spi_basic():
    """Test SPI basic configuration."""
    print("\n" + "=" * 60)
    print("  Test 5: SPI Basic Configuration")
    print("=" * 60 + "\n")

    spi = STM32SPIv1(index=1, base=0x40013000)

    # Configure as master, 8-bit, clock/256
    # CR1: MSTR | BR[2:0]=111 | SPE
    cr1 = (1 << 2) | (7 << 3) | (1 << 6)  # MSTR | BR=111 | SPE
    spi.write(spi.base + spi.CR1, 4, cr1)
    cr1_read, _ = spi.read(spi.base + spi.CR1, 4)
    print(f"  CR1 = 0x{cr1_read:08X}")

    # Check status
    sr, _ = spi.read(spi.base + spi.SR, 4)
    txe = (sr >> 1) & 1
    bsy = (sr >> 7) & 1
    print(f"  SR = 0x{sr:04X} (TXE={txe}, BSY={bsy})")

    # Transmit data
    spi.write(spi.base + spi.DR, 4, 0xAA)

    # Check SR after TX
    sr_after, _ = spi.read(spi.base + spi.SR, 4)
    txe_after = (sr_after >> 1) & 1
    print(f"  SR after TX: 0x{sr_after:04X} (TXE={txe_after})")

    success = (txe == 1) and (txe_after == 1)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_timer_basic():
    """Test basic timer operation."""
    print("\n" + "=" * 60)
    print("  Test 6: Timer Basic Operations")
    print("=" * 60 + "\n")

    timer = STM32GeneralTimer(index=2, base=0x40000000, is_32bit=True)

    # Configure prescaler and auto-reload
    timer.write(timer.base + timer.PSC, 4, 15999)  # 16MHz/16000 = 1kHz
    timer.write(timer.base + timer.ARR, 4, 999)    # Period = 1000 = 1 second

    psc, _ = timer.read(timer.base + timer.PSC, 4)
    arr, _ = timer.read(timer.base + timer.ARR, 4)
    print(f"  PSC = {psc}, ARR = {arr}")

    # Enable update interrupt
    timer.write(timer.base + timer.DIER, 4, 1)  # UIE

    # Enable counter
    timer.write(timer.base + timer.CR1, 4, 1)  # CEN
    cr1, _ = timer.read(timer.base + timer.CR1, 4)
    print(f"  CR1 = 0x{cr1:04X} (CEN={cr1 & 1})")

    # Read counter
    cnt, _ = timer.read(timer.base + timer.CNT, 4)
    print(f"  CNT = {cnt}")

    # Simulate ticks
    for _ in range(100):
        timer.tick()
    cnt, _ = timer.read(timer.base + timer.CNT, 4)
    print(f"  CNT after 100 ticks = {cnt}")

    success = (cr1 & 1) == 1
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_dma_basic():
    """Test DMA basic configuration (DMAv1 channel-based)."""
    print("\n" + "=" * 60)
    print("  Test 7: DMA Basic Configuration")
    print("=" * 60 + "\n")

    # Use DMAv1 (F1-style channel-based DMA)
    from slab_stm32 import STM32DMAv1
    dma = STM32DMAv1(index=1, base=0x40020000)

    # Channel 1 register offsets
    ch1_base = dma.CHANNEL_OFFSET  # 0x08
    ch1_ccr = ch1_base + dma.CCR
    ch1_cndtr = ch1_base + dma.CNDTR
    ch1_cpar = ch1_base + dma.CPAR
    ch1_cmar = ch1_base + dma.CMAR

    # Configure Channel 1
    # DIR=1 (read from memory), MINC=1, PSIZE=8bit, MSIZE=8bit
    ccr = dma.CCR_DIR | dma.CCR_MINC
    dma.write(dma.base + ch1_ccr, 4, ccr)

    # Set addresses
    dma.write(dma.base + ch1_cpar, 4, 0x40011004)   # USART DR
    dma.write(dma.base + ch1_cmar, 4, 0x20000000)   # Memory buffer
    dma.write(dma.base + ch1_cndtr, 4, 16)          # Transfer count

    # Read back
    ccr_read, _ = dma.read(dma.base + ch1_ccr, 4)
    cndtr, _ = dma.read(dma.base + ch1_cndtr, 4)
    cpar, _ = dma.read(dma.base + ch1_cpar, 4)
    cmar, _ = dma.read(dma.base + ch1_cmar, 4)
    print(f"  CCR1 = 0x{ccr_read:08X}")
    print(f"  CNDTR1 = {cndtr}")
    print(f"  CPAR1 = 0x{cpar:08X}")
    print(f"  CMAR1 = 0x{cmar:08X}")

    # Enable channel
    dma.write(dma.base + ch1_ccr, 4, ccr_read | dma.CCR_EN)
    ccr_read, _ = dma.read(dma.base + ch1_ccr, 4)
    enabled = ccr_read & dma.CCR_EN
    print(f"  CCR1 after enable = 0x{ccr_read:08X} (EN={enabled})")

    # Check ISR
    isr, _ = dma.read(dma.base + dma.ISR, 4)
    print(f"  ISR = 0x{isr:08X}")

    success = (cndtr == 16) and (enabled != 0)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_adc_basic():
    """Test ADC basic configuration."""
    print("\n" + "=" * 60)
    print("  Test 8: ADC Basic Operations")
    print("=" * 60 + "\n")

    adc = STM32ADCv2(index=1, base=0x40012000)

    # Enable ADC
    adc.write(adc.base + adc.CR2, 4, 1)  # ADON
    cr2, _ = adc.read(adc.base + adc.CR2, 4)
    print(f"  CR2 = 0x{cr2:08X} (ADON={cr2 & 1})")

    # Configure channel (single conversion, channel 0)
    adc.write(adc.base + adc.SQR3, 4, 0)  # Channel 0 first
    adc.write(adc.base + adc.SQR1, 4, 0)  # 1 conversion

    # Set sample time
    adc.write(adc.base + adc.SMPR2, 4, 0x7)  # 480 cycles for ch0

    # Start conversion
    adc.write(adc.base + adc.CR2, 4, cr2 | (1 << 30))  # SWSTART

    # Check status
    sr, _ = adc.read(adc.base + adc.SR, 4)
    eoc = (sr >> 1) & 1
    print(f"  SR = 0x{sr:08X} (EOC={eoc})")

    # Read data
    dr, _ = adc.read(adc.base + adc.DR, 4)
    print(f"  DR = {dr} (12-bit ADC value)")

    success = (cr2 & 1) == 1
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_rng():
    """Test RNG random number generator."""
    print("\n" + "=" * 60)
    print("  Test 9: RNG Random Number Generator")
    print("=" * 60 + "\n")

    rng = STM32RNG(base=0x50060800)

    # Enable RNG
    rng.write(rng.base + rng.CR, 4, 4)  # RNGEN
    cr, _ = rng.read(rng.base + rng.CR, 4)
    print(f"  CR = 0x{cr:08X} (RNGEN={cr >> 2 & 1})")

    # Generate random numbers
    values = []
    for i in range(5):
        # Check DRDY
        sr, _ = rng.read(rng.base + rng.SR, 4)
        drdy = sr & 1

        # Read data
        dr, _ = rng.read(rng.base + rng.DR, 4)
        values.append(dr)
        print(f"  RNG[{i}] = 0x{dr:08X} (DRDY={drdy})")

    # Check randomness (all different)
    unique = len(set(values))
    print(f"\n  Unique values: {unique}/5")

    success = unique >= 3  # At least 3 unique values
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_crc():
    """Test CRC calculation unit."""
    print("\n" + "=" * 60)
    print("  Test 10: CRC Calculation Unit")
    print("=" * 60 + "\n")

    crc = STM32CRC(base=0x40023000)

    # Reset CRC
    crc.write(crc.base + crc.CR, 4, 1)  # RESET

    # Calculate CRC of test data
    test_data = [0x12345678, 0x9ABCDEF0, 0x55AA55AA]
    for data in test_data:
        crc.write(crc.base + crc.DR, 4, data)

    # Read result
    result, _ = crc.read(crc.base + crc.DR, 4)
    print(f"  Input data: {[hex(x) for x in test_data]}")
    print(f"  CRC result: 0x{result:08X}")

    # Verify it changes with different input
    crc.write(crc.base + crc.CR, 4, 1)  # Reset
    crc.write(crc.base + crc.DR, 4, 0xFFFFFFFF)
    result2, _ = crc.read(crc.base + crc.DR, 4)
    print(f"  CRC of 0xFFFFFFFF: 0x{result2:08X}")

    success = (result != 0) and (result != result2)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_iwdg():
    """Test Independent Watchdog."""
    print("\n" + "=" * 60)
    print("  Test 11: Independent Watchdog")
    print("=" * 60 + "\n")

    iwdg = STM32IWDG(base=0x40003000)

    # Unlock registers
    iwdg.write(iwdg.base + iwdg.KR, 4, 0x5555)
    print("  Unlocked registers")

    # Set prescaler and reload
    iwdg.write(iwdg.base + iwdg.PR, 4, 4)    # /64
    iwdg.write(iwdg.base + iwdg.RLR, 4, 500)  # Reload value

    pr, _ = iwdg.read(iwdg.base + iwdg.PR, 4)
    rlr, _ = iwdg.read(iwdg.base + iwdg.RLR, 4)
    print(f"  PR = {pr}, RLR = {rlr}")

    # Enable watchdog
    iwdg.write(iwdg.base + iwdg.KR, 4, 0xCCCC)
    print("  Watchdog enabled")

    # Simulate ticks (shouldn't trigger reset)
    reset = False
    for _ in range(100):
        if iwdg.tick():
            reset = True
            break

    print(f"  After 100 ticks: reset={reset}")

    # Reload
    iwdg.write(iwdg.base + iwdg.KR, 4, 0xAAAA)
    print("  Watchdog reloaded")

    success = not reset and (pr == 4) and (rlr == 500)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_f407_peripheral_set():
    """Test STM32F407 peripheral set creation."""
    print("\n" + "=" * 60)
    print("  Test 12: STM32F407 Peripheral Set")
    print("=" * 60 + "\n")

    peripherals = STM32F407PeripheralSet(log=logging.getLogger('STM32F407'))

    # Check peripheral count
    count = len(peripherals.peripherals)
    print(f"  Total peripherals: {count}")

    # Check key peripherals exist
    checks = [
        ("RCC", hasattr(peripherals, 'rcc')),
        ("GPIOA", 'A' in peripherals.gpio),
        ("USART1", hasattr(peripherals, 'usart1')),
        ("SPI1", hasattr(peripherals, 'spi1')),
        ("TIM2", hasattr(peripherals, 'tim2')),
        ("DMA1", hasattr(peripherals, 'dma1')),
        ("ADC1", hasattr(peripherals, 'adc1')),
        ("RNG", hasattr(peripherals, 'rng')),
    ]

    all_pass = True
    for name, exists in checks:
        status = "✓" if exists else "✗"
        print(f"    {status} {name}")
        if not exists:
            all_pass = False

    # Test GPIO via peripheral set
    print("\n  Testing GPIOA via peripheral set...")
    gpioa = peripherals.gpio['A']
    gpioa.write(gpioa.base + gpioa.MODER, 4, 0x00000400)  # PA5 output
    gpioa.write(gpioa.base + gpioa.BSRR, 4, 0x00000020)   # Set PA5
    odr, _ = gpioa.read(gpioa.base + gpioa.ODR, 4)
    pa5_set = (odr & 0x20) != 0
    print(f"    PA5 set: {pa5_set}")

    success = all_pass and pa5_set
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def main():
    """Run all STM32 tests."""
    print()
    print("=" * 60)
    print("   STM32 Peripheral Emulation Test Suite")
    print("=" * 60)

    tests = [
        ("GPIOv2 Basic", test_gpio_v2_basic),
        ("GPIOv1 Basic", test_gpio_v1_basic),
        ("RCC Clock Config", test_rcc_clock_config),
        ("USART Basic", test_usart_basic),
        ("SPI Basic", test_spi_basic),
        ("Timer Basic", test_timer_basic),
        ("DMA Basic", test_dma_basic),
        ("ADC Basic", test_adc_basic),
        ("RNG", test_rng),
        ("CRC", test_crc),
        ("IWDG", test_iwdg),
        ("F407 Peripheral Set", test_f407_peripheral_set),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            log.error(f"Test '{name}' failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("   Test Summary")
    print("=" * 60 + "\n")

    passed = 0
    failed = 0
    for name, result in results:
        status = "PASS" if result else "FAIL"
        symbol = "✓" if result else "✗"
        print(f"  {symbol} {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print()
    print(f"  Total: {len(results)} tests, {passed} passed, {failed} failed")
    print()

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
