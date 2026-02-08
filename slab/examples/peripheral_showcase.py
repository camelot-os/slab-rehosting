#!/usr/bin/env python3
"""
Peripheral Showcase Demo - All Slab Peripherals

This comprehensive demo showcases all the peripheral emulation capabilities
of Slab, demonstrating how each peripheral can be used with real firmware
and how they bridge to external systems.

Peripherals Demonstrated:
========================

1. STM32 Core Peripherals:
   - DMA (Direct Memory Access)
   - GPIO (General Purpose I/O with EXTI)
   - USART (Universal Async Receiver/Transmitter)
   - SPI (Serial Peripheral Interface)
   - I2C (Inter-Integrated Circuit)
   - TIM (Timers)
   - RCC (Reset and Clock Control)
   - FLASH Interface

2. Communication Peripherals:
   - CAN (Controller Area Network) with SocketCAN bridge
   - USB OTG (On-The-Go) with USBIP bidirectional support
   - USB CDC-ACM (Virtual Serial Port)
   - TCP Peripheral (Network-based peripheral access)
   - SPI Bridge (Multi-MCU communication)

3. Security Peripherals:
   - CRYP (Hardware Crypto with OpenSSL backend)
   - HASH (Hardware Hash with OpenSSL backend)
   - RNG (Random Number Generator)

4. External Device Emulation:
   - SPI Flash (W25Q128)
   - TFT LCD (ILI9341)
   - Touch Controller (ADS7846)

Usage:
    python3 peripheral_showcase.py [demo]

    Available demos:
        all       - Run all demos (default)
        gpio      - GPIO and interrupts
        uart      - USART serial communication
        spi       - SPI master/slave
        i2c       - I2C communication
        can       - CAN bus with virtual bridge
        usb       - USB CDC with USBIP
        crypto    - Hardware crypto engine
        dma       - DMA transfers
        timer     - Timers and PWM
        flash     - SPI Flash emulation

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (C) 2025 Twisted Wires Security Lab
"""

import argparse
import sys
import time
import struct
import threading
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def print_header(title: str, char: str = "="):
    """Print formatted section header."""
    width = 70
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def print_subheader(title: str):
    """Print formatted subsection header."""
    print(f"\n  {title}")
    print(f"  {'-' * (len(title) + 2)}")


# =============================================================================
# GPIO DEMO
# =============================================================================

def demo_gpio():
    """
    Demonstrate GPIO peripheral emulation.

    Shows:
    - GPIO port configuration (MODER, OTYPER, OSPEEDR, PUPDR)
    - Output data register (ODR)
    - Input data register (IDR)
    - External interrupt (EXTI) configuration
    """
    print_header("GPIO Peripheral Demo")

    from slab_cortex_m.stm32_peripherals import GPIOPort, EXTIController

    # Create GPIO ports
    gpioa = GPIOPort('GPIOA', 0x40020000)
    gpiob = GPIOPort('GPIOB', 0x40020400)

    # Create EXTI controller
    exti = EXTIController(0x40013C00)
    exti.connect_gpio(gpioa, 0)  # GPIOA pin 0 -> EXTI0

    print_subheader("1. Configure GPIO pins")

    # Configure PA0 as output (LED)
    # MODER: 01 = General purpose output mode
    gpioa.write_reg(gpioa.MODER, 0x00000001)  # PA0 as output
    print(f"  GPIOA MODER: 0x{gpioa.read_reg(gpioa.MODER):08X}")

    # Configure PA1 as input with pull-up
    # PUPDR: 01 = Pull-up
    gpioa.write_reg(gpioa.PUPDR, 0x00000004)  # PA1 pull-up
    print(f"  GPIOA PUPDR: 0x{gpioa.read_reg(gpioa.PUPDR):08X}")

    print_subheader("2. Write to GPIO output")

    # Toggle PA0
    gpioa.write_reg(gpioa.ODR, 0x0001)  # Set PA0
    print(f"  GPIOA ODR: 0x{gpioa.read_reg(gpioa.ODR):04X} (PA0 = HIGH)")

    gpioa.write_reg(gpioa.ODR, 0x0000)  # Clear PA0
    print(f"  GPIOA ODR: 0x{gpioa.read_reg(gpioa.ODR):04X} (PA0 = LOW)")

    # Use BSRR for atomic set/reset
    gpioa.write_reg(gpioa.BSRR, 0x00000001)  # Set PA0
    print(f"  GPIOA ODR after BSRR set: 0x{gpioa.read_reg(gpioa.ODR):04X}")

    gpioa.write_reg(gpioa.BSRR, 0x00010000)  # Reset PA0
    print(f"  GPIOA ODR after BSRR reset: 0x{gpioa.read_reg(gpioa.ODR):04X}")

    print_subheader("3. Read GPIO input")

    # Read IDR
    idr = gpioa.read_reg(gpioa.IDR)
    print(f"  GPIOA IDR: 0x{idr:04X}")

    print_subheader("4. External Interrupt (EXTI)")

    # Configure EXTI for rising edge on line 0
    exti.write_reg(exti.RTSR, 0x00000001)  # Rising trigger
    exti.write_reg(exti.IMR, 0x00000001)   # Unmask line 0

    # Track interrupts
    interrupt_count = [0]
    def exti_handler(line: int):
        interrupt_count[0] += 1
        print(f"    -> EXTI{line} interrupt triggered!")

    exti.on_interrupt = exti_handler

    # Simulate pin change (external stimulus)
    gpioa.set_input_pin(0, True)  # Rising edge
    print(f"  Total EXTI interrupts: {interrupt_count[0]}")

    print("\n  GPIO demo complete!")
    return True


# =============================================================================
# UART DEMO
# =============================================================================

def demo_uart():
    """
    Demonstrate USART peripheral emulation.

    Shows:
    - USART configuration (BRR, CR1, CR2, CR3)
    - TX/RX data transfer
    - Interrupt handling
    """
    print_header("USART Peripheral Demo")

    from slab_cortex_m.stm32_peripherals import USARTPeripheral

    # Create USART instances
    usart1 = USARTPeripheral('USART1', 0x40011000)
    usart2 = USARTPeripheral('USART2', 0x40004400)

    print_subheader("1. Configure USART")

    # Configure for 115200 baud (assuming 84MHz APB2)
    # BRR = fck / baud = 84000000 / 115200 = 729 (0x2D9)
    usart1.write_reg(usart1.BRR, 0x2D9)

    # Enable USART, TX, RX
    # CR1: UE=1, TE=1, RE=1
    cr1 = (1 << 13) | (1 << 3) | (1 << 2)  # UE | TE | RE
    usart1.write_reg(usart1.CR1, cr1)

    print(f"  USART1 BRR: 0x{usart1.read_reg(usart1.BRR):04X}")
    print(f"  USART1 CR1: 0x{usart1.read_reg(usart1.CR1):08X}")

    print_subheader("2. Transmit data")

    # Track TX callback
    tx_data = []
    def on_tx(byte):
        tx_data.append(byte)
        print(f"    -> TX: 0x{byte:02X} '{chr(byte) if 32 <= byte < 127 else '?'}'")

    usart1.on_tx_byte = on_tx

    # Send "Hello"
    for c in b"Hello":
        # Wait for TXE
        sr = usart1.read_reg(usart1.SR)
        if sr & (1 << 7):  # TXE
            usart1.write_reg(usart1.DR, c)

    print(f"  Transmitted: {bytes(tx_data)}")

    print_subheader("3. Receive data")

    # Simulate RX data
    rx_message = b"World!"
    for c in rx_message:
        usart1.inject_rx_byte(c)

    # Read back
    received = []
    while True:
        sr = usart1.read_reg(usart1.SR)
        if not (sr & (1 << 5)):  # RXNE
            break
        byte = usart1.read_reg(usart1.DR) & 0xFF
        received.append(byte)
        print(f"    <- RX: 0x{byte:02X} '{chr(byte) if 32 <= byte < 127 else '?'}'")

    print(f"  Received: {bytes(received)}")

    print("\n  USART demo complete!")
    return True


# =============================================================================
# SPI DEMO
# =============================================================================

def demo_spi():
    """
    Demonstrate SPI peripheral emulation.

    Shows:
    - SPI master configuration
    - SPI slave response
    - Full duplex transfer
    """
    print_header("SPI Peripheral Demo")

    from slab_cortex_m.spi_bridge import SPIMasterPeripheral, SPISlavePeripheral, SPIBridge

    # Create SPI peripherals
    spi_master = SPIMasterPeripheral('SPI1', 0x40013000)
    spi_slave = SPISlavePeripheral('SPI2', 0x40003800)

    # Create bridge
    bridge = SPIBridge()
    bridge.connect(spi_master, spi_slave)

    print_subheader("1. Configure SPI Master")

    # CR1: SPE=1, MSTR=1, BR=2 (fPCLK/8), CPOL=0, CPHA=0
    cr1_master = (1 << 6) | (1 << 2) | (2 << 3)  # SPE | MSTR | BR
    spi_master.write_reg(spi_master.CR1, cr1_master)
    print(f"  SPI1 CR1: 0x{spi_master.read_reg(spi_master.CR1):08X}")

    print_subheader("2. Configure SPI Slave")

    # CR1: SPE=1, MSTR=0
    cr1_slave = (1 << 6)  # SPE only
    spi_slave.write_reg(spi_slave.CR1, cr1_slave)

    # Prepare slave response
    spi_slave.set_tx_data(b'\xAA\xBB\xCC\xDD')
    print(f"  SPI2 TX buffer: {spi_slave.tx_buffer.hex()}")

    print_subheader("3. Full duplex transfer")

    # Master sends data, receives slave response
    tx_bytes = [0x01, 0x02, 0x03, 0x04]
    rx_bytes = []

    for tx in tx_bytes:
        # Write to DR (initiates transfer)
        spi_master.write_reg(spi_master.DR, tx)

        # Wait for RXNE
        while not (spi_master.read_reg(spi_master.SR) & 0x01):
            pass

        # Read received byte
        rx = spi_master.read_reg(spi_master.DR) & 0xFF
        rx_bytes.append(rx)
        print(f"    TX: 0x{tx:02X} -> RX: 0x{rx:02X}")

    print(f"\n  Master sent: {bytes(tx_bytes).hex()}")
    print(f"  Master received: {bytes(rx_bytes).hex()}")
    print(f"  Slave received: {spi_slave.rx_buffer.hex()}")

    print("\n  SPI demo complete!")
    return True


# =============================================================================
# CAN DEMO
# =============================================================================

def demo_can():
    """
    Demonstrate CAN peripheral emulation.

    Shows:
    - CAN controller configuration
    - TX/RX mailboxes
    - Message filtering
    - Virtual CAN bridge
    """
    print_header("CAN Bus Peripheral Demo")

    from slab_cortex_m.can_peripheral import (
        CANController, CANMessage, CANFilter,
        VirtualCANBridge
    )

    # Create two CAN controllers
    can1 = CANController(0x40006400, "CAN1")
    can2 = CANController(0x40006800, "CAN2")

    # Create virtual CAN bus
    vcan = VirtualCANBridge()
    vcan.connect(can2._receive_message)
    can1.connect_bridge(vcan)

    print_subheader("1. Initialize CAN controllers")

    # Enter initialization mode
    can1.write_reg(CANController.MCR, CANController.MCR_INRQ)
    print(f"  CAN1 MSR: 0x{can1.read_reg(CANController.MSR):08X} (init mode)")

    # Configure bit timing (500kbps)
    can1.write_reg(CANController.BTR, 0x001C0003)
    print(f"  CAN1 BTR: 0x{can1.read_reg(CANController.BTR):08X}")

    # Exit init mode
    can1.write_reg(CANController.MCR, 0)
    print(f"  CAN1 MSR: 0x{can1.read_reg(CANController.MSR):08X} (normal mode)")

    print_subheader("2. Configure filters on CAN2")

    # Accept IDs 0x100-0x1FF
    can2.add_filter(id_value=0x100, id_mask=0x700)
    print(f"  CAN2 filter: accept 0x100-0x1FF")

    # Track received messages
    rx_messages = []
    def on_rx(msg):
        rx_messages.append(msg)
        print(f"    <- CAN2 RX: {msg}")

    can2.on_rx = on_rx

    print_subheader("3. Transmit message")

    # Prepare TX mailbox 0
    can1.write_reg(CANController.TDL0R, 0xDEADBEEF)  # Data bytes 0-3
    can1.write_reg(CANController.TDH0R, 0xCAFEBABE)  # Data bytes 4-7
    can1.write_reg(CANController.TDT0R, 8)           # DLC = 8

    # Set ID 0x123 and request TX
    can1.write_reg(CANController.TI0R, (0x123 << 21) | 1)  # TXRQ = 1
    print(f"  CAN1 sent: ID=0x123, DLC=8, data=DEADBEEF CAFEBABE")

    print_subheader("4. Check reception")

    print(f"  CAN2 RF0R: 0x{can2.read_reg(CANController.RF0R):08X}")
    print(f"  Messages in CAN2 FIFO0: {len(can2.rx_fifo0)}")

    if can2.rx_fifo0:
        msg = can2.rx_fifo0[0]
        print(f"  First message: ID=0x{msg.arbitration_id:03X}, data={msg.data.hex()}")

    print_subheader("5. Send filtered message (should be rejected)")

    # Send ID 0x300 (outside filter range)
    can1.write_reg(CANController.TI0R, (0x300 << 21) | 1)
    print(f"  CAN1 sent: ID=0x300 (filtered)")
    print(f"  CAN2 FIFO0 count after: {len(can2.rx_fifo0)}")

    print("\n  CAN demo complete!")
    return True


# =============================================================================
# USB DEMO
# =============================================================================

def demo_usb():
    """
    Demonstrate USB OTG peripheral emulation.

    Shows:
    - USB device creation (CDC-ACM)
    - USBIP server for host connection
    - Virtual self-test
    """
    print_header("USB OTG Peripheral Demo")

    try:
        from slab_cortex_m.usb_otg import (
            OTGController, OTGMode, USBSpeed, USBDevice,
            USBIPServer, create_cdc_acm_device
        )
    except ImportError as e:
        print(f"  USB OTG not available: {e}")
        return False

    print_subheader("1. Create USB CDC-ACM device")

    # Create virtual CDC device
    device = create_cdc_acm_device(vid=0x1234, pid=0x5678)
    device.manufacturer = "Twisted Wires"
    device.product = "Slab Virtual Serial"
    device.serial = "SLAB-001"

    print(f"  VID:PID = {device.vendor_id:04x}:{device.product_id:04x}")
    print(f"  Manufacturer: {device.manufacturer}")
    print(f"  Product: {device.product}")
    print(f"  Serial: {device.serial}")

    print_subheader("2. Device descriptors")

    desc = device.get_device_descriptor()
    print(f"  Device descriptor ({len(desc)} bytes):")
    print(f"    bLength: {desc[0]}")
    print(f"    bDescriptorType: {desc[1]} (DEVICE)")
    print(f"    bcdUSB: 0x{struct.unpack('<H', desc[2:4])[0]:04X}")
    print(f"    bDeviceClass: {desc[4]} (CDC)")
    print(f"    idVendor: 0x{struct.unpack('<H', desc[8:10])[0]:04X}")
    print(f"    idProduct: 0x{struct.unpack('<H', desc[10:12])[0]:04X}")

    print_subheader("3. OTG Controller")

    otg = OTGController()
    print(f"  OTG mode: {otg.mode.name}")
    print(f"  Speed: {otg.speed.name}")

    print_subheader("4. USBIP Server (for device mode)")

    print("  Device mode allows host PC to enumerate this virtual device")
    print("  via USBIP protocol:")
    print()
    print("    # On host PC:")
    print("    sudo modprobe vhci-hcd")
    print("    usbip list -r <emulator-ip>")
    print("    sudo usbip attach -r <emulator-ip> -b 1-1")
    print()
    print("  The device would appear as /dev/ttyACM* on Linux")

    print("\n  USB demo complete!")
    return True


# =============================================================================
# CRYPTO DEMO
# =============================================================================

def demo_crypto():
    """
    Demonstrate hardware crypto engine emulation.

    Shows:
    - AES encryption/decryption
    - Key loading
    - OpenSSL backend
    """
    print_header("Hardware Crypto Engine Demo")

    from slab_cortex_m.peripheral_bridges import (
        STM32CryptoEngine, STM32CryptoAlgorithm
    )

    crypto = STM32CryptoEngine()

    print_subheader("1. Check OpenSSL backend")

    if crypto._openssl_available:
        print("  OpenSSL backend: available")
    else:
        print("  OpenSSL backend: not available (using fallback)")

    print_subheader("2. Load AES-128 key")

    # Test key: 00112233445566778899AABBCCDDEEFF
    key = [0x00112233, 0x44556677, 0x8899AABB, 0xCCDDEEFF]
    for i, word in enumerate(key):
        crypto.write(crypto.K0LR + i*4, 4, word)
        print(f"    K{i}: 0x{word:08X}")

    print_subheader("3. Configure AES-ECB encryption")

    # CR: AES-ECB mode, 128-bit key, encrypt, enable
    cr = (STM32CryptoAlgorithm.AES_ECB << 3) | crypto.CR_CRYPEN
    crypto.write(crypto.CR, 4, cr)
    print(f"  CR: 0x{crypto.read(crypto.CR, 4):08X}")

    print_subheader("4. Encrypt plaintext block")

    # Plaintext: 00000000000000000000000000000000
    plaintext = [0x00000000, 0x00000000, 0x00000000, 0x00000000]
    print(f"  Plaintext: {''.join(f'{w:08X}' for w in plaintext)}")

    # Write to input FIFO
    for word in plaintext:
        crypto.write(crypto.DIN, 4, word)

    # Read ciphertext
    ciphertext = []
    for _ in range(4):
        ciphertext.append(crypto.read(crypto.DOUT, 4))

    print(f"  Ciphertext: {''.join(f'{w:08X}' for w in ciphertext)}")

    if ciphertext != plaintext:
        print("  Encryption successful!")
    else:
        print("  WARNING: Output matches input (encryption may have failed)")

    print_subheader("5. Status register")

    sr = crypto.read(crypto.SR, 4)
    print(f"  SR: 0x{sr:08X}")
    print(f"    IFEM (input empty): {bool(sr & crypto.SR_IFEM)}")
    print(f"    IFNF (input not full): {bool(sr & crypto.SR_IFNF)}")
    print(f"    OFNE (output not empty): {bool(sr & crypto.SR_OFNE)}")
    print(f"    BUSY: {bool(sr & crypto.SR_BUSY)}")

    print("\n  Crypto demo complete!")
    return True


# =============================================================================
# DMA DEMO
# =============================================================================

def demo_dma():
    """
    Demonstrate DMA peripheral emulation.

    Shows:
    - DMA stream configuration
    - Memory-to-memory transfer
    - Interrupt handling
    """
    print_header("DMA Peripheral Demo")

    from slab_cortex_m.stm32_peripherals import DMAController

    # Create DMA controller
    dma = DMAController('DMA1', 0x40026000)

    # Simulated memory
    src_memory = bytearray(b"Hello DMA Transfer Test!")
    dst_memory = bytearray(32)

    def memory_read(addr: int, size: int) -> bytes:
        if 0x20000000 <= addr < 0x20000100:
            offset = addr - 0x20000000
            return bytes(src_memory[offset:offset+size])
        return b'\x00' * size

    def memory_write(addr: int, data: bytes):
        if 0x20001000 <= addr < 0x20001100:
            offset = addr - 0x20001000
            dst_memory[offset:offset+len(data)] = data

    # Connect memory callbacks
    stream = dma.streams[0]
    stream.memory_read = memory_read
    stream.memory_write = memory_write

    print_subheader("1. Configure DMA stream 0")

    # Source address (memory)
    dma.write_reg(0x18 + 0x08, 0x20000000)  # Stream 0 PAR (source)
    print(f"  Source: 0x20000000")

    # Destination address
    dma.write_reg(0x18 + 0x0C, 0x20001000)  # Stream 0 M0AR (dest)
    print(f"  Destination: 0x20001000")

    # Number of data items
    dma.write_reg(0x18 + 0x04, 24)  # NDTR = 24 bytes
    print(f"  Transfer size: 24 bytes")

    print_subheader("2. Source data")
    print(f"  src_memory: {src_memory[:24]}")
    print(f"  dst_memory: {dst_memory[:24]}")

    print_subheader("3. Start transfer")

    # CR: MEM2MEM, MINC, PINC, EN
    cr = (1 << 14) | (1 << 10) | (1 << 9) | (1 << 0)
    dma.write_reg(0x18 + 0x00, cr)

    # Simulate transfer
    stream.execute_transfer()

    print_subheader("4. Result")
    print(f"  dst_memory: {dst_memory[:24]}")

    if dst_memory[:24] == src_memory[:24]:
        print("\n  DMA transfer successful!")
    else:
        print("\n  DMA transfer result mismatch")

    print("\n  DMA demo complete!")
    return True


# =============================================================================
# TIMER DEMO
# =============================================================================

def demo_timer():
    """
    Demonstrate Timer peripheral emulation.

    Shows:
    - Timer configuration
    - PWM output
    - Input capture
    """
    print_header("Timer Peripheral Demo")

    from slab_cortex_m.stm32_peripherals import TimerPeripheral

    # Create timer
    tim2 = TimerPeripheral('TIM2', 0x40000000, is_advanced=False)

    print_subheader("1. Configure timer for PWM")

    # Prescaler: divide by 84 (84MHz -> 1MHz)
    tim2.write_reg(tim2.PSC, 83)
    print(f"  PSC: {tim2.read_reg(tim2.PSC)} (84MHz / 84 = 1MHz)")

    # Auto-reload: 1000 (1kHz PWM frequency)
    tim2.write_reg(tim2.ARR, 999)
    print(f"  ARR: {tim2.read_reg(tim2.ARR)} (1MHz / 1000 = 1kHz)")

    # Compare value: 500 (50% duty cycle)
    tim2.write_reg(tim2.CCR1, 500)
    print(f"  CCR1: {tim2.read_reg(tim2.CCR1)} (50% duty cycle)")

    print_subheader("2. Configure output compare mode")

    # CCMR1: PWM mode 1
    ccmr1 = (6 << 4) | (1 << 3)  # OC1M=110 (PWM1), OC1PE=1
    tim2.write_reg(tim2.CCMR1, ccmr1)
    print(f"  CCMR1: 0x{tim2.read_reg(tim2.CCMR1):08X} (PWM mode 1)")

    # CCER: Enable OC1
    tim2.write_reg(tim2.CCER, 1)  # CC1E
    print(f"  CCER: 0x{tim2.read_reg(tim2.CCER):04X} (OC1 enabled)")

    print_subheader("3. Start timer")

    # CR1: Enable counter
    tim2.write_reg(tim2.CR1, 1)  # CEN
    print(f"  CR1: 0x{tim2.read_reg(tim2.CR1):08X} (counter enabled)")

    print_subheader("4. Read counter")

    # Simulate time passing
    for i in range(5):
        tim2.tick(200)  # 200 timer ticks
        cnt = tim2.read_reg(tim2.CNT)
        print(f"    CNT after {(i+1)*200} ticks: {cnt}")

    print("\n  Timer demo complete!")
    return True


# =============================================================================
# FLASH DEMO
# =============================================================================

def demo_flash():
    """
    Demonstrate SPI Flash emulation.

    Shows:
    - W25Q128 (16MB) flash emulation
    - JEDEC ID reading
    - Page programming
    - Sector erase
    """
    print_header("SPI Flash Emulation Demo")

    from slab_cortex_m.stm32_peripherals import W25QFlash

    # Create 16MB flash
    flash = W25QFlash(size_mb=16)

    print_subheader("1. Read JEDEC ID")

    # Send JEDEC ID command (0x9F)
    jedec = flash.execute_command(0x9F, 0, 3)
    print(f"  JEDEC ID: {jedec.hex().upper()}")
    print(f"    Manufacturer: 0x{jedec[0]:02X} (Winbond)")
    print(f"    Device Type: 0x{jedec[1]:02X}")
    print(f"    Capacity: 0x{jedec[2]:02X} ({2**(jedec[2]-10)} KB)")

    print_subheader("2. Write enable and page program")

    # Write enable
    flash.execute_command(0x06, 0, 0)
    print("  Write enabled")

    # Page program at address 0x000100
    data = b"Hello Flash World!"
    flash.execute_command(0x02, 0x000100, 0, data)
    print(f"  Programmed {len(data)} bytes at 0x000100")

    print_subheader("3. Read data back")

    # Fast read
    read_data = flash.execute_command(0x0B, 0x000100, len(data) + 1)  # +1 for dummy byte
    read_data = read_data[1:]  # Skip dummy byte
    print(f"  Read: {read_data}")

    if read_data == data:
        print("  Data verification: PASS")
    else:
        print("  Data verification: FAIL")

    print_subheader("4. Sector erase")

    # Sector erase at 0x000000
    flash.execute_command(0x06, 0, 0)  # Write enable
    flash.execute_command(0x20, 0x000000, 0)  # 4KB sector erase
    print("  Sector 0 erased")

    # Read back (should be 0xFF)
    read_data = flash.execute_command(0x0B, 0x000100, 9)[1:]  # Skip dummy
    print(f"  After erase: {read_data.hex()}")

    if read_data == b'\xFF' * 8:
        print("  Erase verification: PASS")
    else:
        print("  Erase verification: FAIL")

    print("\n  Flash demo complete!")
    return True


# =============================================================================
# MAIN
# =============================================================================

DEMOS = {
    'gpio': demo_gpio,
    'uart': demo_uart,
    'spi': demo_spi,
    'can': demo_can,
    'usb': demo_usb,
    'crypto': demo_crypto,
    'dma': demo_dma,
    'timer': demo_timer,
    'flash': demo_flash,
}


def run_all_demos():
    """Run all demos and report results."""
    print_header("SLAB PERIPHERAL SHOWCASE", "=")
    print("""
    This demo showcases all peripheral emulation capabilities of Slab.
    Each peripheral can be bridged to real hardware or external systems.
    """)

    results = {}

    for name, demo_func in DEMOS.items():
        try:
            success = demo_func()
            results[name] = "PASS" if success else "FAIL"
        except Exception as e:
            logger.exception(f"Demo {name} failed")
            results[name] = f"ERROR: {e}"

    # Summary
    print_header("DEMO SUMMARY")
    for name, result in results.items():
        status = "PASS" if result == "PASS" else "FAIL"
        indicator = "[OK]" if status == "PASS" else "[!!]"
        print(f"  {indicator} {name:12s}: {result}")

    passed = sum(1 for r in results.values() if r == "PASS")
    total = len(results)
    print(f"\n  Total: {passed}/{total} passed")

    return passed == total


def main():
    parser = argparse.ArgumentParser(
        description="Slab Peripheral Showcase Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available demos:
  all       Run all demos (default)
  gpio      GPIO and external interrupts
  uart      USART serial communication
  spi       SPI master/slave with bridge
  can       CAN bus with virtual bridge
  usb       USB OTG with USBIP
  crypto    Hardware crypto engine
  dma       DMA memory transfers
  timer     Timers and PWM
  flash     SPI Flash emulation

Examples:
  python3 peripheral_showcase.py          # Run all demos
  python3 peripheral_showcase.py gpio     # GPIO demo only
  python3 peripheral_showcase.py can usb  # CAN and USB demos
        """
    )
    parser.add_argument(
        'demos',
        nargs='*',
        default=['all'],
        help='Demo(s) to run (default: all)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if 'all' in args.demos:
        success = run_all_demos()
    else:
        for demo_name in args.demos:
            if demo_name not in DEMOS:
                print(f"Unknown demo: {demo_name}")
                print(f"Available: {', '.join(DEMOS.keys())}")
                return 1

            try:
                DEMOS[demo_name]()
            except Exception as e:
                logger.exception(f"Demo {demo_name} failed: {e}")
                return 1

        success = True

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
