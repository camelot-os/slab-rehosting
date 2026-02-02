# Slab Peripherals

SVD-based peripheral modeling and auto-generation for the Slab security analysis framework.

## Features

- **SVD Composer**: Parse, compose, and generate SVD files for any microcontroller
- **MMIO Log Parser**: Extract peripheral behavior from emulation traces
- **Interactive Browser**: Explore SVD device definitions interactively
- **Auto-Generation**: Generate peripheral models from patterns and templates

## Installation

```bash
# Standalone installation
pip install slab-peripherals

# With LLM-assisted generation
pip install slab-peripherals[llm]

# Development installation
pip install -e .[dev]
```

## Quick Start

### 1. Parse an SVD File

```python
from slab_peripherals import SVDParser

# Parse SVD file for your MCU
parser = SVDParser("STM32F407.svd")
device = parser.parse()

# List all peripherals
print(f"Device: {device.name}")
for periph in device.peripherals:
    print(f"  {periph.name}: 0x{periph.base_address:08X}")
```

### 2. Access Register Definitions

```python
from slab_peripherals import SVDParser

device = SVDParser("STM32F407.svd").parse()

# Get GPIOA peripheral
gpioa = device.get_peripheral("GPIOA")

# List registers
for reg in gpioa.registers:
    print(f"  {reg.name} @ offset 0x{reg.address_offset:04X}")
    for field in reg.fields:
        print(f"    {field.name}: bits [{field.bit_offset}:{field.bit_offset + field.bit_width - 1}]")
```

### 3. Compose SVD from Multiple Sources

```python
from slab_peripherals import SVDComposer

# Create composer
composer = SVDComposer()

# Add base device
composer.add_base_device("STM32F4_base.svd")

# Add custom peripheral
composer.add_peripheral_from_yaml("custom_peripheral.yaml")

# Override specific registers
composer.override_register("GPIOA", "ODR", reset_value=0x00000000)

# Export composed SVD
composer.export("composed_device.svd")
```

### 4. Parse MMIO Logs to Discover Peripherals

```python
from slab_peripherals import MMIOLogParser

# Parse QEMU MMIO log
parser = MMIOLogParser("mmio_trace.log")
accesses = parser.parse()

# Group by peripheral region
regions = parser.group_by_region()
for region, ops in regions.items():
    print(f"Region 0x{region:08X}: {len(ops)} accesses")
    # Show common patterns
    patterns = parser.detect_patterns(ops)
    for pattern in patterns:
        print(f"  Pattern: {pattern.type} - {pattern.description}")
```

### 5. Generate Peripheral Model from Template

```python
from slab_peripherals import PeripheralGenerator, PeripheralTemplate

# Create generator with base template
template = PeripheralTemplate.load("gpio_template.yaml")
generator = PeripheralGenerator(template)

# Customize for target
generator.set_base_address(0x40020000)
generator.set_register_count(12)
generator.add_interrupt("GPIOA_IRQ", 6)

# Generate Python peripheral model
code = generator.generate_python()
print(code)

# Or generate C header
header = generator.generate_c_header()
print(header)
```

### 6. Interactive SVD Browser

```python
from slab_peripherals import InteractiveBrowser

# Launch interactive browser
browser = InteractiveBrowser("STM32F407.svd")
browser.run()

# Commands available:
#   list peripherals    - Show all peripherals
#   show GPIOA         - Show peripheral details
#   fields GPIOA.ODR   - Show register fields
#   search timer       - Search for matching peripherals
#   export GPIOA       - Export peripheral to YAML
```

## Example: Create Custom Peripheral Definition

```yaml
# custom_uart.yaml
name: CUSTOM_UART
base_address: 0x40010000
size: 0x400
description: Custom UART peripheral

registers:
  - name: DR
    offset: 0x00
    size: 32
    reset_value: 0x00000000
    description: Data register
    fields:
      - name: DATA
        bit_offset: 0
        bit_width: 8
        access: read-write
        description: Transmit/Receive data

  - name: SR
    offset: 0x04
    size: 32
    reset_value: 0x00000000
    description: Status register
    fields:
      - name: TXE
        bit_offset: 7
        bit_width: 1
        access: read-only
        description: Transmit data register empty
      - name: RXNE
        bit_offset: 5
        bit_width: 1
        access: read-only
        description: Read data register not empty
      - name: TC
        bit_offset: 6
        bit_width: 1
        access: read-only
        description: Transmission complete

  - name: CR1
    offset: 0x0C
    size: 32
    reset_value: 0x00000000
    description: Control register 1
    fields:
      - name: UE
        bit_offset: 0
        bit_width: 1
        access: read-write
        description: UART enable
      - name: TE
        bit_offset: 3
        bit_width: 1
        access: read-write
        description: Transmitter enable
      - name: RE
        bit_offset: 2
        bit_width: 1
        access: read-write
        description: Receiver enable

interrupts:
  - name: UART_IRQ
    value: 37
    description: UART global interrupt
```

## Integration with QEMU

```python
from slab_peripherals import SVDParser
from slab_cortex_m import TCPPeripheralBridge

# Parse SVD for register definitions
device = SVDParser("STM32F407.svd").parse()
gpioa = device.get_peripheral("GPIOA")

# Connect to QEMU peripheral bridge
bridge = TCPPeripheralBridge("localhost", 5555)
bridge.connect()

# Use SVD definitions for type-safe access
def read_gpio_odr(bridge, periph):
    odr = periph.get_register("ODR")
    addr = periph.base_address + odr.address_offset
    return bridge.read32(addr)

def write_gpio_odr(bridge, periph, value):
    odr = periph.get_register("ODR")
    addr = periph.base_address + odr.address_offset
    bridge.write32(addr, value)

# Toggle LED on PA5
current = read_gpio_odr(bridge, gpioa)
write_gpio_odr(bridge, gpioa, current ^ (1 << 5))
```

## Author

Mathieu Renard <mathieu.renard@twistedwires.io>

## License

GPL-2.0-or-later OR Apache-2.0
