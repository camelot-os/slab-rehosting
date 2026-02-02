# Slab Cortex-M

ARM Cortex-M emulation core for the Slab security analysis framework.

## Features

- **Peripheral Bridges**: TCP and shared memory bridges for QEMU peripheral export
- **SVD Parsing**: Automatic peripheral register discovery
- **Multiple CPU Support**: M0, M0+, M3, M4, M7, M23, M33, M55, M85
- **STM32 Emulation**: Full peripheral models for STM32 series

## Installation

```bash
# Standalone installation
pip install slab-cortex-m

# With GUI support
pip install slab-cortex-m[gui]

# Development installation
pip install -e .[dev]
```

## Quick Start

### 1. Connect to QEMU Peripheral Bridge

```python
from slab_cortex_m import TCPPeripheralBridge

# Connect to QEMU peripheral bridge
bridge = TCPPeripheralBridge("localhost", 5555)
bridge.connect()

# Read/write peripheral registers
value = bridge.read32(0x40000000)
bridge.write32(0x40000000, 0x12345678)

# Read memory block
data = bridge.read_memory(0x20000000, 256)

# Write memory block
bridge.write_memory(0x20000000, b"Hello, World!")

# Cleanup
bridge.disconnect()
```

### 2. GPIO Control

```python
from slab_cortex_m import TCPPeripheralBridge

bridge = TCPPeripheralBridge("localhost", 5555)
bridge.connect()

# STM32F4 GPIO addresses
GPIOA_BASE = 0x40020000
GPIO_MODER = 0x00    # Mode register
GPIO_ODR = 0x14      # Output data register
GPIO_IDR = 0x10      # Input data register

# Configure PA5 as output (LED)
moder = bridge.read32(GPIOA_BASE + GPIO_MODER)
moder &= ~(0x3 << 10)  # Clear PA5 mode bits
moder |= (0x1 << 10)   # Set as output
bridge.write32(GPIOA_BASE + GPIO_MODER, moder)

# Toggle LED
def toggle_led():
    odr = bridge.read32(GPIOA_BASE + GPIO_ODR)
    odr ^= (1 << 5)  # Toggle PA5
    bridge.write32(GPIOA_BASE + GPIO_ODR, odr)

# Blink 10 times
import time
for _ in range(10):
    toggle_led()
    time.sleep(0.5)
```

### 3. UART Communication

```python
from slab_cortex_m import TCPPeripheralBridge

bridge = TCPPeripheralBridge("localhost", 5555)
bridge.connect()

# STM32F4 USART1 addresses
USART1_BASE = 0x40011000
USART_SR = 0x00     # Status register
USART_DR = 0x04     # Data register

def uart_send_byte(byte):
    """Send single byte via UART."""
    # Wait for TX empty
    while not (bridge.read32(USART1_BASE + USART_SR) & 0x80):
        pass
    bridge.write32(USART1_BASE + USART_DR, byte)

def uart_receive_byte():
    """Receive single byte from UART."""
    # Wait for RX not empty
    while not (bridge.read32(USART1_BASE + USART_SR) & 0x20):
        pass
    return bridge.read32(USART1_BASE + USART_DR) & 0xFF

def uart_send_string(s):
    """Send string via UART."""
    for c in s.encode():
        uart_send_byte(c)

# Send message
uart_send_string("Hello from Python!\r\n")
```

### 4. SPI Communication

```python
from slab_cortex_m import TCPPeripheralBridge

bridge = TCPPeripheralBridge("localhost", 5555)
bridge.connect()

# STM32F4 SPI1 addresses
SPI1_BASE = 0x40013000
SPI_CR1 = 0x00     # Control register 1
SPI_SR = 0x08      # Status register
SPI_DR = 0x0C      # Data register

def spi_transfer(tx_byte):
    """Full-duplex SPI transfer."""
    # Wait for TX buffer empty
    while not (bridge.read32(SPI1_BASE + SPI_SR) & 0x02):
        pass

    # Write TX data
    bridge.write32(SPI1_BASE + SPI_DR, tx_byte)

    # Wait for RX buffer not empty
    while not (bridge.read32(SPI1_BASE + SPI_SR) & 0x01):
        pass

    # Read RX data
    return bridge.read32(SPI1_BASE + SPI_DR) & 0xFF

# Read SPI flash ID (typical sequence)
def read_flash_id():
    cs_low()
    spi_transfer(0x9F)  # READ JEDEC ID command
    mfg = spi_transfer(0x00)
    mem_type = spi_transfer(0x00)
    capacity = spi_transfer(0x00)
    cs_high()
    return (mfg, mem_type, capacity)
```

### 5. Shared Memory Interface (Fast)

```python
from slab_cortex_m import SHMPeripheralBridge

# Use shared memory for high-speed communication
shm = SHMPeripheralBridge("/slab_periph")
shm.connect()

# Same API as TCP bridge but much faster
value = shm.read32(0x40020000)
shm.write32(0x40020014, 0x00000020)

# Bulk transfers are especially fast
data = shm.read_memory(0x20000000, 65536)  # 64KB
```

### 6. CAN Bus Communication

```python
from slab_cortex_m import CANPeripheral

# Connect to CAN peripheral
can = CANPeripheral("localhost", 5556)
can.connect()

# Send CAN frame
can.send_frame(
    arbitration_id=0x123,
    data=b"\x01\x02\x03\x04",
    extended=False
)

# Receive CAN frame with timeout
frame = can.receive_frame(timeout=1.0)
if frame:
    print(f"ID: 0x{frame.arbitration_id:03X}")
    print(f"Data: {frame.data.hex()}")

# Register callback for incoming frames
def on_can_frame(frame):
    print(f"Received: {frame}")

can.set_callback(on_can_frame)
can.start_receive_loop()
```

### 7. USB Device Emulation

```python
from slab_cortex_m import USBOTGPeripheral

# Connect to USB OTG peripheral
usb = USBOTGPeripheral("localhost", 5557)
usb.connect()

# Configure as CDC device
usb.configure_cdc(
    vid=0x0483,
    pid=0x5740,
    manufacturer="STMicroelectronics",
    product="Virtual COM Port"
)

# Send/receive CDC data
usb.cdc_send(b"Hello USB!\r\n")
data = usb.cdc_receive(64, timeout=1.0)

# Or use USBIP for full USB stack emulation
from slab_cortex_m import USBIPClient

client = USBIPClient("localhost", 3240)
client.connect()
devices = client.list_devices()
client.attach_device(devices[0])
```

### 8. Timer and PWM

```python
from slab_cortex_m import TCPPeripheralBridge

bridge = TCPPeripheralBridge("localhost", 5555)
bridge.connect()

# STM32F4 TIM2 addresses (32-bit timer)
TIM2_BASE = 0x40000000
TIM_CR1 = 0x00     # Control register 1
TIM_CNT = 0x24     # Counter
TIM_PSC = 0x28     # Prescaler
TIM_ARR = 0x2C     # Auto-reload

# Configure timer: 1MHz tick (168MHz / 168)
bridge.write32(TIM2_BASE + TIM_PSC, 167)
bridge.write32(TIM2_BASE + TIM_ARR, 0xFFFFFFFF)

# Enable timer
bridge.write32(TIM2_BASE + TIM_CR1, 0x01)

# Read counter value
def get_timer_us():
    return bridge.read32(TIM2_BASE + TIM_CNT)

# Measure execution time
start = get_timer_us()
# ... do something ...
elapsed = get_timer_us() - start
print(f"Elapsed: {elapsed} microseconds")
```

### 9. DMA Operations

```python
from slab_cortex_m import TCPPeripheralBridge

bridge = TCPPeripheralBridge("localhost", 5555)
bridge.connect()

# Configure DMA for memory-to-memory transfer
DMA2_BASE = 0x40026400
DMA_S0CR = 0x10    # Stream 0 control register
DMA_S0NDTR = 0x14  # Stream 0 number of data
DMA_S0PAR = 0x18   # Stream 0 peripheral address
DMA_S0M0AR = 0x1C  # Stream 0 memory 0 address

def dma_memory_copy(src: int, dst: int, size: int):
    """Copy memory using DMA."""
    # Disable stream first
    bridge.write32(DMA2_BASE + DMA_S0CR, 0)

    # Set addresses
    bridge.write32(DMA2_BASE + DMA_S0PAR, src)
    bridge.write32(DMA2_BASE + DMA_S0M0AR, dst)
    bridge.write32(DMA2_BASE + DMA_S0NDTR, size)

    # Configure: MEM2MEM, 32-bit, increment both
    cr = (1 << 14) | (2 << 13) | (2 << 11) | (1 << 10) | (1 << 9) | (2 << 6)
    bridge.write32(DMA2_BASE + DMA_S0CR, cr)

    # Enable stream
    bridge.write32(DMA2_BASE + DMA_S0CR, cr | 1)

# Copy 1KB from SRAM to backup region
dma_memory_copy(0x20000000, 0x20010000, 1024)
```

### 10. Flash Memory Access

```python
from slab_cortex_m import TCPPeripheralBridge

bridge = TCPPeripheralBridge("localhost", 5555)
bridge.connect()

# STM32F4 Flash interface
FLASH_BASE = 0x40023C00
FLASH_KEYR = 0x04
FLASH_SR = 0x0C
FLASH_CR = 0x10

def flash_unlock():
    """Unlock flash for programming."""
    bridge.write32(FLASH_BASE + FLASH_KEYR, 0x45670123)
    bridge.write32(FLASH_BASE + FLASH_KEYR, 0xCDEF89AB)

def flash_wait_busy():
    """Wait for flash operation to complete."""
    while bridge.read32(FLASH_BASE + FLASH_SR) & 0x10000:
        pass

def flash_write_word(address: int, data: int):
    """Write 32-bit word to flash."""
    flash_unlock()
    flash_wait_busy()

    # Enable programming
    cr = bridge.read32(FLASH_BASE + FLASH_CR)
    bridge.write32(FLASH_BASE + FLASH_CR, cr | 0x01)

    # Write data
    bridge.write32(address, data)

    # Wait for completion
    flash_wait_busy()

    # Disable programming
    bridge.write32(FLASH_BASE + FLASH_CR, cr)
```

## Architecture Support

| CPU | Pipeline | FPU | DSP | TrustZone |
|-----|----------|-----|-----|-----------|
| Cortex-M0 | 3-stage | No | No | No |
| Cortex-M0+ | 2-stage | No | No | No |
| Cortex-M3 | 3-stage | No | No | No |
| Cortex-M4 | 3-stage | SP | Yes | No |
| Cortex-M7 | 6-stage | DP | Yes | No |
| Cortex-M23 | 2-stage | No | No | Yes |
| Cortex-M33 | 3-stage | SP | Yes | Yes |
| Cortex-M55 | 4-stage | DP | Yes | Yes |

## References

### ARM Documentation

- [ARM Cortex-M Technical Reference Manuals](https://developer.arm.com/documentation)
- [ARMv7-M Architecture Reference Manual](https://developer.arm.com/documentation/ddi0403/latest/)
- [ARMv8-M Architecture Reference Manual](https://developer.arm.com/documentation/ddi0553/latest/)

### STM32 Resources

- [STM32 Reference Manuals](https://www.st.com/en/microcontrollers-microprocessors/stm32-32-bit-arm-cortex-mcus.html#documentation)
- [SVD Files Repository](https://github.com/cmsis-svd/cmsis-svd-data)

### Security Research

- **RDP Bypass**
  - Obermaier & Tatschner, "Shedding too much Light on a Microcontroller's Firmware Protection", WOOT 2017
  - [Paper](https://www.usenix.org/conference/woot17/workshop-program/presentation/obermaier)

- **Debug Interface Attacks**
  - Vasselle et al., "Breaking Mobile Firmware Encryption through SCA", BlackHat USA 2019
  - [Paper](https://i.blackhat.com/USA-19/Thursday/us-19-Vasselle-Breaking-Mobile-Firmware-Encryption-Through-SCA.pdf)

### Notable CVEs

- **CVE-2017-18269**: STM32F4 RDP Level 1 bypass
- **CVE-2020-27212**: LPC55S69 secure boot bypass
- **CVE-2020-8004**: nRF52 debug access bypass via voltage glitching
- **CVE-2021-20315**: STM32L4 debug protection bypass

## Author

Mathieu Renard <mathieu.renard@twistedwires.io>

## License

GPL-2.0-or-later
