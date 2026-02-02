#!/usr/bin/env python3
"""
NRF Peripheral Test Suite

Comprehensive tests for Nordic nRF peripheral emulation:
- GPIO and GPIOTE
- UARTE (EasyDMA UART)
- SPIM (EasyDMA SPI Master)
- TWIM (EasyDMA I2C Master)
- TIMER
- RTC
- SAADC
- RNG
- ECB (AES)
- CCM (AES-CCM)
- RADIO
- CLOCK/POWER
- NVMC

Run:
    python3 test_nrf.py

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import logging
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent))

from slab_nrf import (
    # GPIO
    NRFGPIO, NRFGPIOTE,
    # Communication
    NRFUARTE, NRFSPIM, NRFTWIM,
    # Timers
    NRFTIMER, NRFRTC,
    # Analog
    NRFSAADC,
    # Security
    NRFRNG, NRFECB, NRFCCM,
    # Radio
    NRFRADIO,
    # System
    NRFPOWER, NRFCLOCK, NRFNVMC,
    # Peripheral Sets
    NRF52840PeripheralSet,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('NRF.Test')


def test_gpio_basic():
    """Test GPIO basic operations."""
    print("\n" + "=" * 60)
    print("  Test 1: GPIO Basic Operations")
    print("=" * 60 + "\n")

    gpio = NRFGPIO(port=0, base=0x50000000)

    # Configure P0.13 as output (LED on most dev boards)
    # DIR register: bit 13 = 1 for output
    gpio.write(gpio.base + gpio.DIRSET, 4, 1 << 13)
    dir_val = gpio.read(gpio.base + gpio.DIR, 4)
    print(f"  DIR after DIRSET: 0x{dir_val:08X}")

    # Set pin high
    gpio.write(gpio.base + gpio.OUTSET, 4, 1 << 13)
    out_val = gpio.read(gpio.base + gpio.OUT, 4)
    print(f"  OUT after OUTSET: 0x{out_val:08X}")

    # Set pin low
    gpio.write(gpio.base + gpio.OUTCLR, 4, 1 << 13)
    out_val = gpio.read(gpio.base + gpio.OUT, 4)
    print(f"  OUT after OUTCLR: 0x{out_val:08X}")

    # Toggle pin
    gpio.write(gpio.base + gpio.OUTSET, 4, 1 << 13)
    out_val = gpio.read(gpio.base + gpio.OUT, 4)
    p13_state = (out_val >> 13) & 1
    print(f"  P0.13 state: {p13_state}")

    # Configure pin function (PIN_CNF)
    # Input, pullup, sense disabled
    pin_cnf = 0x0C  # PULL = Pullup (0b11)
    gpio.write(gpio.base + gpio.PIN_CNF_BASE + 13 * 4, 4, pin_cnf)
    cnf_read = gpio.read(gpio.base + gpio.PIN_CNF_BASE + 13 * 4, 4)
    print(f"  PIN_CNF[13] = 0x{cnf_read:08X}")

    success = (dir_val & (1 << 13)) != 0 and p13_state == 1
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_gpiote():
    """Test GPIOTE (GPIO Task/Event) operations."""
    print("\n" + "=" * 60)
    print("  Test 2: GPIOTE Task/Event Operations")
    print("=" * 60 + "\n")

    gpiote = NRFGPIOTE(base=0x40006000)

    # Configure channel 0 for task mode on P0.13
    # CONFIG: MODE=Task(3), PSEL=13, PORT=0, POLARITY=Toggle(3)
    config = (3 << 0) | (13 << 8) | (0 << 13) | (3 << 16)
    gpiote.write(gpiote.base + gpiote.CONFIG_BASE, 4, config)
    config_read = gpiote.read(gpiote.base + gpiote.CONFIG_BASE, 4)
    print(f"  CONFIG[0] = 0x{config_read:08X}")

    # Trigger task
    gpiote.write(gpiote.base + gpiote.TASKS_OUT_BASE, 4, 1)
    print("  Triggered TASKS_OUT[0]")

    # Check event (should be cleared after task)
    event = gpiote.read(gpiote.base + gpiote.EVENTS_IN_BASE, 4)
    print(f"  EVENTS_IN[0] = {event}")

    # Enable interrupt
    gpiote.write(gpiote.base + gpiote.INTENSET, 4, 1)
    inten = gpiote.read(gpiote.base + gpiote.INTENSET, 4)
    print(f"  INTENSET = 0x{inten:08X}")

    success = (config_read == config)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_uarte():
    """Test UARTE (EasyDMA UART) operations."""
    print("\n" + "=" * 60)
    print("  Test 3: UARTE (EasyDMA UART)")
    print("=" * 60 + "\n")

    uarte = NRFUARTE(index=0, base=0x40002000)

    # Configure baud rate (115200)
    uarte.write(uarte.base + uarte.BAUDRATE, 4, 0x01D7E000)
    baud = uarte.read(uarte.base + uarte.BAUDRATE, 4)
    print(f"  BAUDRATE = 0x{baud:08X}")

    # Configure pins (TX=6, RX=8)
    uarte.write(uarte.base + uarte.PSEL_TXD, 4, 6)
    uarte.write(uarte.base + uarte.PSEL_RXD, 4, 8)
    psel_txd = uarte.read(uarte.base + uarte.PSEL_TXD, 4)
    psel_rxd = uarte.read(uarte.base + uarte.PSEL_RXD, 4)
    print(f"  PSEL.TXD = {psel_txd}, PSEL.RXD = {psel_rxd}")

    # Configure TX buffer (EasyDMA)
    uarte.write(uarte.base + uarte.TXD_PTR, 4, 0x20000000)
    uarte.write(uarte.base + uarte.TXD_MAXCNT, 4, 16)
    txd_ptr = uarte.read(uarte.base + uarte.TXD_PTR, 4)
    txd_maxcnt = uarte.read(uarte.base + uarte.TXD_MAXCNT, 4)
    print(f"  TXD.PTR = 0x{txd_ptr:08X}, TXD.MAXCNT = {txd_maxcnt}")

    # Enable UART
    uarte.write(uarte.base + uarte.ENABLE, 4, 8)  # UARTE enable
    enable = uarte.read(uarte.base + uarte.ENABLE, 4)
    print(f"  ENABLE = {enable}")

    # Start TX task
    uarte.write(uarte.base + uarte.TASKS_STARTTX, 4, 1)
    print("  Started TX task")

    # Check ENDTX event
    endtx = uarte.read(uarte.base + uarte.EVENTS_ENDTX, 4)
    print(f"  EVENTS_ENDTX = {endtx}")

    success = (enable == 8) and (txd_maxcnt == 16)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_spim():
    """Test SPIM (EasyDMA SPI Master) operations."""
    print("\n" + "=" * 60)
    print("  Test 4: SPIM (EasyDMA SPI Master)")
    print("=" * 60 + "\n")

    spim = NRFSPIM(index=0, base=0x40003000)

    # Configure frequency (4MHz)
    spim.write(spim.base + spim.FREQUENCY, 4, 0x40000000)
    freq = spim.read(spim.base + spim.FREQUENCY, 4)
    print(f"  FREQUENCY = 0x{freq:08X}")

    # Configure pins (SCK=25, MOSI=24, MISO=23)
    spim.write(spim.base + spim.PSEL_SCK, 4, 25)
    spim.write(spim.base + spim.PSEL_MOSI, 4, 24)
    spim.write(spim.base + spim.PSEL_MISO, 4, 23)
    sck = spim.read(spim.base + spim.PSEL_SCK, 4)
    mosi = spim.read(spim.base + spim.PSEL_MOSI, 4)
    miso = spim.read(spim.base + spim.PSEL_MISO, 4)
    print(f"  PSEL: SCK={sck}, MOSI={mosi}, MISO={miso}")

    # Configure buffers
    spim.write(spim.base + spim.TXD_PTR, 4, 0x20000100)
    spim.write(spim.base + spim.TXD_MAXCNT, 4, 8)
    spim.write(spim.base + spim.RXD_PTR, 4, 0x20000200)
    spim.write(spim.base + spim.RXD_MAXCNT, 4, 8)

    txd_maxcnt = spim.read(spim.base + spim.TXD_MAXCNT, 4)
    rxd_maxcnt = spim.read(spim.base + spim.RXD_MAXCNT, 4)
    print(f"  TXD.MAXCNT = {txd_maxcnt}, RXD.MAXCNT = {rxd_maxcnt}")

    # Enable SPI
    spim.write(spim.base + spim.ENABLE, 4, 7)
    enable = spim.read(spim.base + spim.ENABLE, 4)
    print(f"  ENABLE = {enable}")

    success = (enable == 7) and (txd_maxcnt == 8)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_timer():
    """Test TIMER operations."""
    print("\n" + "=" * 60)
    print("  Test 5: TIMER Operations")
    print("=" * 60 + "\n")

    timer = NRFTIMER(index=0)

    # Configure 32-bit timer mode
    timer.write(timer.base + timer.MODE, 4, 0)      # Timer mode
    timer.write(timer.base + timer.BITMODE, 4, 3)   # 32-bit
    timer.write(timer.base + timer.PRESCALER, 4, 4) # 16MHz/16 = 1MHz

    mode = timer.read(timer.base + timer.MODE, 4)
    bitmode = timer.read(timer.base + timer.BITMODE, 4)
    prescaler = timer.read(timer.base + timer.PRESCALER, 4)
    print(f"  MODE = {mode}, BITMODE = {bitmode}, PRESCALER = {prescaler}")

    # Set compare value (CC_BASE + 0*4 = CC[0])
    timer.write(timer.base + timer.CC_BASE, 4, 1000)
    cc0 = timer.read(timer.base + timer.CC_BASE, 4)
    print(f"  CC[0] = {cc0}")

    # Enable shortcuts (COMPARE0 -> CLEAR)
    timer.write(timer.base + timer.SHORTS, 4, 1)
    shorts = timer.read(timer.base + timer.SHORTS, 4)
    print(f"  SHORTS = 0x{shorts:04X}")

    # Start timer
    timer.write(timer.base + timer.TASKS_START, 4, 1)
    print("  Started timer")

    # Simulate ticks
    for _ in range(500):
        timer.tick()

    # Capture counter (TASKS_CAPTURE_BASE + 0*4 = TASKS_CAPTURE[0])
    timer.write(timer.base + timer.TASKS_CAPTURE_BASE, 4, 1)
    cc0 = timer.read(timer.base + timer.CC_BASE, 4)
    print(f"  Counter captured to CC[0] = {cc0}")

    # Check compare event (EVENTS_COMPARE_BASE + 0*4 = EVENTS_COMPARE[0])
    event = timer.read(timer.base + timer.EVENTS_COMPARE_BASE, 4)
    print(f"  EVENTS_COMPARE[0] = {event}")

    success = (bitmode == 3) and (prescaler == 4)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_rtc():
    """Test RTC (Real-Time Counter) operations."""
    print("\n" + "=" * 60)
    print("  Test 6: RTC (Real-Time Counter)")
    print("=" * 60 + "\n")

    rtc = NRFRTC(index=0)

    # Configure prescaler (32768Hz / 8 = 4096Hz)
    rtc.write(rtc.base + rtc.PRESCALER, 4, 7)
    prescaler = rtc.read(rtc.base + rtc.PRESCALER, 4)
    print(f"  PRESCALER = {prescaler}")

    # Set compare value (CC_BASE + 0*4 = CC[0])
    rtc.write(rtc.base + rtc.CC_BASE, 4, 4096)  # 1 second
    cc0 = rtc.read(rtc.base + rtc.CC_BASE, 4)
    print(f"  CC[0] = {cc0}")

    # Enable compare interrupt
    rtc.write(rtc.base + rtc.INTENSET, 4, 1 << 16)  # COMPARE0
    inten = rtc.read(rtc.base + rtc.INTENSET, 4)
    print(f"  INTENSET = 0x{inten:08X}")

    # Start RTC
    rtc.write(rtc.base + rtc.TASKS_START, 4, 1)
    print("  Started RTC")

    # Simulate ticks (RTC uses tick_lfclk)
    for _ in range(100):
        rtc.tick_lfclk()

    # Read counter
    counter = rtc.read(rtc.base + rtc.COUNTER, 4)
    print(f"  COUNTER = {counter}")

    success = (prescaler == 7)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_saadc():
    """Test SAADC (Successive Approximation ADC) operations."""
    print("\n" + "=" * 60)
    print("  Test 7: SAADC Operations")
    print("=" * 60 + "\n")

    saadc = NRFSAADC(base=0x40007000)

    # Configure resolution (14-bit)
    saadc.write(saadc.base + saadc.RESOLUTION, 4, 3)  # 14-bit
    resolution = saadc.read(saadc.base + saadc.RESOLUTION, 4)
    print(f"  RESOLUTION = {resolution} (14-bit)")

    # Configure channel 0 (AIN0) - CH_BASE + ch*16 = PSELP for channel 0
    ch0_pselp = 1  # AIN0
    saadc.write(saadc.base + saadc.CH_BASE, 4, ch0_pselp)
    pselp = saadc.read(saadc.base + saadc.CH_BASE, 4)
    print(f"  CH[0].PSELP = {pselp}")

    # Configure result buffer
    saadc.write(saadc.base + saadc.RESULT_PTR, 4, 0x20000300)
    saadc.write(saadc.base + saadc.RESULT_MAXCNT, 4, 1)
    maxcnt = saadc.read(saadc.base + saadc.RESULT_MAXCNT, 4)
    print(f"  RESULT.MAXCNT = {maxcnt}")

    # Enable SAADC
    saadc.write(saadc.base + saadc.ENABLE, 4, 1)
    enable = saadc.read(saadc.base + saadc.ENABLE, 4)
    print(f"  ENABLE = {enable}")

    # Start sample task
    saadc.write(saadc.base + saadc.TASKS_SAMPLE, 4, 1)
    print("  Started sample task")

    # Check END event
    end = saadc.read(saadc.base + saadc.EVENTS_END, 4)
    print(f"  EVENTS_END = {end}")

    success = (enable == 1) and (resolution == 3)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_rng():
    """Test RNG (Random Number Generator) operations."""
    print("\n" + "=" * 60)
    print("  Test 8: RNG Operations")
    print("=" * 60 + "\n")

    rng = NRFRNG(base=0x4000D000)

    # Enable bias correction
    rng.write(rng.base + rng.CONFIG, 4, 1)
    config = rng.read(rng.base + rng.CONFIG, 4)
    print(f"  CONFIG = {config} (bias correction enabled)")

    # Start RNG
    rng.write(rng.base + rng.TASKS_START, 4, 1)
    print("  Started RNG")

    # Generate random values
    values = []
    for i in range(5):
        # Wait for VALRDY
        rng.tick()
        event = rng.read(rng.base + rng.EVENTS_VALRDY, 4)

        # Read value
        value = rng.read(rng.base + rng.VALUE, 4)
        values.append(value)
        print(f"  RNG[{i}] = 0x{value:02X} (VALRDY={event})")

        # Clear event
        rng.write(rng.base + rng.EVENTS_VALRDY, 4, 0)

    # Check randomness
    unique = len(set(values))
    print(f"\n  Unique values: {unique}/5")

    success = unique >= 3
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_ecb():
    """Test ECB (AES ECB) operations."""
    print("\n" + "=" * 60)
    print("  Test 9: ECB (AES-128 ECB)")
    print("=" * 60 + "\n")

    ecb = NRFECB(base=0x4000E000)

    # Set ECBDATAPTR (points to key + plaintext + ciphertext)
    ecb.write(ecb.base + ecb.ECBDATAPTR, 4, 0x20000400)
    dataptr = ecb.read(ecb.base + ecb.ECBDATAPTR, 4)
    print(f"  ECBDATAPTR = 0x{dataptr:08X}")

    # Start encryption task
    ecb.write(ecb.base + ecb.TASKS_STARTECB, 4, 1)
    print("  Started ECB encryption")

    # Check ENDECB event
    endecb = ecb.read(ecb.base + ecb.EVENTS_ENDECB, 4)
    print(f"  EVENTS_ENDECB = {endecb}")

    # Test using convenience method
    key = bytes(16)  # All zeros
    plaintext = bytes(16)  # All zeros
    ciphertext = ecb.encrypt(key, plaintext)
    print(f"  Key:        {key.hex()}")
    print(f"  Plaintext:  {plaintext.hex()}")
    print(f"  Ciphertext: {ciphertext.hex()}")

    # Verify ciphertext is not equal to plaintext
    success = (ciphertext != plaintext) and (len(ciphertext) == 16)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_radio_basic():
    """Test RADIO basic operations."""
    print("\n" + "=" * 60)
    print("  Test 10: RADIO Basic Operations")
    print("=" * 60 + "\n")

    radio = NRFRADIO(base=0x40001000)

    # Configure for BLE 1Mbit
    radio.write(radio.base + radio.MODE, 4, 3)  # BLE_1MBIT
    mode = radio.read(radio.base + radio.MODE, 4)
    print(f"  MODE = {mode} (BLE_1MBIT)")

    # Set frequency (2402 MHz = channel 0)
    radio.write(radio.base + radio.FREQUENCY, 4, 2)  # 2400 + 2 = 2402 MHz
    freq = radio.read(radio.base + radio.FREQUENCY, 4)
    print(f"  FREQUENCY = {freq} (2400 + {freq} MHz)")

    # Set TX power (0 dBm)
    radio.write(radio.base + radio.TXPOWER, 4, 0)
    txpower = radio.read(radio.base + radio.TXPOWER, 4)
    print(f"  TXPOWER = {txpower} dBm")

    # Configure packet format
    # S0=1 byte, LENGTH=8 bits, S1=0
    pcnf0 = (8 << 0) | (1 << 8)
    radio.write(radio.base + radio.PCNF0, 4, pcnf0)
    pcnf0_read = radio.read(radio.base + radio.PCNF0, 4)
    print(f"  PCNF0 = 0x{pcnf0_read:08X}")

    # Max packet length, whitening, big-endian
    pcnf1 = (255 << 0) | (3 << 16) | (1 << 25)
    radio.write(radio.base + radio.PCNF1, 4, pcnf1)
    pcnf1_read = radio.read(radio.base + radio.PCNF1, 4)
    print(f"  PCNF1 = 0x{pcnf1_read:08X}")

    # Set packet pointer
    radio.write(radio.base + radio.PACKETPTR, 4, 0x20000500)
    packetptr = radio.read(radio.base + radio.PACKETPTR, 4)
    print(f"  PACKETPTR = 0x{packetptr:08X}")

    # Configure CRC (3 bytes, skip address)
    radio.write(radio.base + radio.CRCCNF, 4, (3 << 0) | (1 << 8))
    radio.write(radio.base + radio.CRCPOLY, 4, 0x00065B)
    radio.write(radio.base + radio.CRCINIT, 4, 0x555555)
    crccnf = radio.read(radio.base + radio.CRCCNF, 4)
    print(f"  CRCCNF = 0x{crccnf:08X}")

    # Check state
    state = radio.read(radio.base + radio.STATE, 4)
    print(f"  STATE = {state}")

    success = (mode == 3) and (freq == 2)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_clock():
    """Test CLOCK operations."""
    print("\n" + "=" * 60)
    print("  Test 11: CLOCK Operations")
    print("=" * 60 + "\n")

    clock = NRFCLOCK(base=0x40000000)

    # Start HFCLK (external crystal) - events are immediate
    clock.write(clock.base + clock.TASKS_HFCLKSTART, 4, 1)
    print("  Started HFCLK")

    # Check HFCLKSTARTED event
    hfclk_started = clock.read(clock.base + clock.EVENTS_HFCLKSTARTED, 4)
    print(f"  EVENTS_HFCLKSTARTED = {hfclk_started}")

    # Check HFCLKSTAT
    hfclkstat = clock.read(clock.base + clock.HFCLKSTAT, 4)
    src = hfclkstat & 1
    state = (hfclkstat >> 16) & 1
    print(f"  HFCLKSTAT = 0x{hfclkstat:08X} (SRC={src}, STATE={state})")

    # Start LFCLK
    clock.write(clock.base + clock.TASKS_LFCLKSTART, 4, 1)
    lfclk_started = clock.read(clock.base + clock.EVENTS_LFCLKSTARTED, 4)
    print(f"  EVENTS_LFCLKSTARTED = {lfclk_started}")

    success = (hfclk_started == 1)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_nvmc():
    """Test NVMC (Non-Volatile Memory Controller) operations."""
    print("\n" + "=" * 60)
    print("  Test 12: NVMC Operations")
    print("=" * 60 + "\n")

    nvmc = NRFNVMC(base=0x4001E000)

    # Check READY status
    ready = nvmc.read(nvmc.base + nvmc.READY, 4)
    print(f"  READY = {ready}")

    # Enable write mode
    nvmc.write(nvmc.base + nvmc.CONFIG, 4, 1)  # WEN
    config = nvmc.read(nvmc.base + nvmc.CONFIG, 4)
    print(f"  CONFIG = {config} (write enabled)")

    # Enable erase mode
    nvmc.write(nvmc.base + nvmc.CONFIG, 4, 2)  # EEN
    config = nvmc.read(nvmc.base + nvmc.CONFIG, 4)
    print(f"  CONFIG = {config} (erase enabled)")

    # Disable (read-only mode)
    nvmc.write(nvmc.base + nvmc.CONFIG, 4, 0)  # REN
    config = nvmc.read(nvmc.base + nvmc.CONFIG, 4)
    print(f"  CONFIG = {config} (read-only)")

    success = (ready == 1)
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def test_nrf52840_peripheral_set():
    """Test NRF52840 peripheral set creation."""
    print("\n" + "=" * 60)
    print("  Test 13: NRF52840 Peripheral Set")
    print("=" * 60 + "\n")

    peripherals = NRF52840PeripheralSet(log=logging.getLogger('NRF52840'))

    # Check peripheral count
    count = len(peripherals.peripherals)
    print(f"  Total peripherals: {count}")

    # Check key peripherals exist
    checks = [
        ("CLOCK", hasattr(peripherals, 'clock')),
        ("POWER", hasattr(peripherals, 'power')),
        ("GPIO0", hasattr(peripherals, 'gpio0')),
        ("GPIO1", hasattr(peripherals, 'gpio1')),
        ("GPIOTE", hasattr(peripherals, 'gpiote')),
        ("UARTE0", hasattr(peripherals, 'uarte0')),
        ("SPIM0", hasattr(peripherals, 'spim0')),
        ("TIMER0", hasattr(peripherals, 'timer0')),
        ("RTC0", hasattr(peripherals, 'rtc0')),
        ("SAADC", hasattr(peripherals, 'saadc')),
        ("RNG", hasattr(peripherals, 'rng')),
        ("ECB", hasattr(peripherals, 'ecb')),
        ("CCM", hasattr(peripherals, 'ccm')),
        ("RADIO", hasattr(peripherals, 'radio')),
        ("NVMC", hasattr(peripherals, 'nvmc')),
    ]

    all_pass = True
    for name, exists in checks:
        status = "✓" if exists else "✗"
        print(f"    {status} {name}")
        if not exists:
            all_pass = False

    # Test GPIO via peripheral set
    print("\n  Testing GPIO0 via peripheral set...")
    gpio0 = peripherals.gpio0
    gpio0.write(gpio0.base + gpio0.DIRSET, 4, 1 << 13)
    gpio0.write(gpio0.base + gpio0.OUTSET, 4, 1 << 13)
    out = gpio0.read(gpio0.base + gpio0.OUT, 4)
    p13_set = (out >> 13) & 1
    print(f"    P0.13 set: {p13_set}")

    # Test RNG
    print("\n  Testing RNG via peripheral set...")
    rng = peripherals.rng
    value = rng.get_random_byte()
    print(f"    Random byte: 0x{value:02X}")

    success = all_pass and p13_set
    print(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def main():
    """Run all NRF tests."""
    print()
    print("=" * 60)
    print("   NRF Peripheral Emulation Test Suite")
    print("=" * 60)

    tests = [
        ("GPIO Basic", test_gpio_basic),
        ("GPIOTE", test_gpiote),
        ("UARTE", test_uarte),
        ("SPIM", test_spim),
        ("TIMER", test_timer),
        ("RTC", test_rtc),
        ("SAADC", test_saadc),
        ("RNG", test_rng),
        ("ECB", test_ecb),
        ("RADIO Basic", test_radio_basic),
        ("CLOCK", test_clock),
        ("NVMC", test_nvmc),
        ("NRF52840 Peripheral Set", test_nrf52840_peripheral_set),
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
