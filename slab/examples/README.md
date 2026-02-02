# MCUemu Firmware Examples

Firmware examples for MCU rehosting with MCUemu, organized by architecture and MCU family.

## Directory Structure

```
examples/
├── cortex-m/                        # ARM Cortex-M architecture
│   ├── stm32/                       # STMicroelectronics STM32
│   │   ├── f405/                    # STM32F405 (Cortex-M4F)
│   │   │   ├── rtos/                # RTOS examples
│   │   │   │   ├── cubemx_blinky/   # STM32 HAL GPIO blink
│   │   │   │   └── freertos_blinky/ # FreeRTOS multi-task
│   │   │   ├── peripherals/         # Peripheral tests
│   │   │   │   ├── i2c_eeprom/
│   │   │   │   ├── spi_flash/
│   │   │   │   └── spi_lcd/
│   │   │   └── demos/               # Demo applications
│   │   │       ├── hello_blink/     # USB CDC demo
│   │   │       └── hello_blink_uart/# UART demo
│   │   ├── f439/                    # STM32F439 (Cortex-M4F + crypto)
│   │   │   ├── peripherals/
│   │   │   │   ├── dma_flash/
│   │   │   │   └── rtc/
│   │   │   └── usb/
│   │   │       └── crypto_cdc/      # AES/SHA over USB CDC
│   │   ├── h745/                    # STM32H745 (dual Cortex-M7/M4)
│   │   │   └── multicore/
│   │   └── l433/                    # STM32L433 (Cortex-M4, low power)
│   │       └── peripherals/
│   │           └── i2c_eeprom/
│   ├── nrf/                         # Nordic Semiconductor
│   │   └── nrf52840/                # nRF52840 (Cortex-M4F + BLE)
│   │       └── peripherals/
│   │           ├── eeprom/
│   │           ├── flash/
│   │           └── qspi/
│   ├── rp2040/                      # Raspberry Pi RP2040
│   │   ├── peripherals/
│   │   │   └── eeprom/
│   │   └── multicore/
│   ├── rp2350/                      # Raspberry Pi RP2350
│   │   └── multicore/
│   └── cross-platform/              # Multi-target RTOS
│       ├── zephyr/                  # Zephyr RTOS
│       └── nuttx/                   # Apache NuttX
├── benchmark/                       # Performance benchmarks
│   └── cortex-m/
├── repos/                           # SDK repositories (setup_repos.sh)
├── scripts/                         # Build/test scripts
└── docs/                            # Documentation
```

## Supported MCU Families

| Family | MCUs | CPU Core | Examples |
|--------|------|----------|----------|
| **STM32F4** | STM32F405, F439 | Cortex-M4F | rtos, peripherals, demos, usb |
| **STM32H7** | STM32H745 | Cortex-M7 + M4 | multicore |
| **STM32L4** | STM32L433 | Cortex-M4 | peripherals |
| **nRF52** | nRF52840 | Cortex-M4F | peripherals |
| **RP2040** | RP2040 | Cortex-M0+ (dual) | peripherals, multicore |
| **RP2350** | RP2350 | Cortex-M33 (dual) | multicore |

## Quick Start

```bash
# 1. Setup required repositories
./scripts/setup_repos.sh

# 2. Build STM32F405 examples
cd cortex-m/stm32/f405/rtos/cubemx_blinky && make
cd ../freertos_blinky && make

# 3. Run full integration tests
python3 scripts/run_all_rtos_tests.py
```

## Example Categories

### RTOS Examples (`cortex-m/stm32/f405/rtos/`)

| Example | Framework | Binary Size | Description |
|---------|-----------|-------------|-------------|
| `cubemx_blinky` | STM32 HAL | 4.3 KB | GPIO LED blink |
| `freertos_blinky` | FreeRTOS | 8.1 KB | Multi-task LED blink |

### Peripheral Tests (`cortex-m/*/peripherals/`)

| MCU | Example | Peripherals |
|-----|---------|-------------|
| STM32F405 | `i2c_eeprom` | I2C, EEPROM |
| STM32F405 | `spi_flash` | SPI, Flash |
| STM32F405 | `spi_lcd` | SPI, LCD |
| STM32F439 | `dma_flash` | DMA, Flash |
| STM32F439 | `rtc` | RTC |
| nRF52840 | `eeprom` | I2C, EEPROM |
| nRF52840 | `flash` | NVMC |
| nRF52840 | `qspi` | QSPI |
| RP2040 | `eeprom` | I2C, EEPROM |

### Multicore Tests (`cortex-m/*/multicore/`)

| MCU | CPU Cores | Test |
|-----|-----------|------|
| STM32H745 | Cortex-M7 + M4 | Dual-core communication |
| RP2040 | Cortex-M0+ x2 | SIO, FIFOs |
| RP2350 | Cortex-M33 x2 | SIO, FIFOs |

### Demos (`cortex-m/stm32/f405/demos/`)

| Example | Interface | Description |
|---------|-----------|-------------|
| `hello_blink` | USB CDC | LED blink + USB serial |
| `hello_blink_uart` | USART2 | LED blink + UART (115200) |

### Cross-Platform RTOS (`cortex-m/cross-platform/`)

| RTOS | Binary | Features |
|------|--------|----------|
| Zephyr | `zephyr/blinky/build/zephyr.bin` | Full GPIO + USART |
| NuttX | `nuttx/build/nuttx.bin` | NSH shell |

## Running with MCUemu

```bash
# TCP proxy mode (default)
python3 python/mcuemu_server.py --port 5555 &
./qemu/build/qemu-system-arm \
    -M slab-cortex-m \
    -global slab-cortex-m.cpu-type=cortex-m4 \
    -global slab-cortex-m.tcp-port=5555 \
    -kernel examples/cortex-m/stm32/f405/rtos/cubemx_blinky/build/blinky.bin \
    -nographic

# SHM proxy mode (faster)
./qemu/build/qemu-system-arm \
    -M slab-cortex-m,proxy-mode=shm,shm-name=/slab_peripheral \
    -kernel firmware.bin -nographic
```

## Peripheral Proxy Performance

| Mode | Throughput | Avg Latency | P99 Latency | Use Case |
|------|------------|-------------|-------------|----------|
| **TCP** | 13K ops/s | 2.8 µs | 7.0 µs | Remote/Docker |
| **SHM** | 133K ops/s | 2.3 µs | 3.8 µs | Local high-performance |

**SHM is ~10x faster** for high-frequency peripheral access.

### Run Benchmark

```bash
python3 scripts/benchmark_proxy.py --firmware cubemx
python3 scripts/benchmark_proxy.py --firmware zephyr --timeout 5
```

See [docs/BENCHMARK_GUIDE.md](docs/BENCHMARK_GUIDE.md) for detailed benchmark documentation.

## MCUemu Test Interface

All examples use a memory-mapped test interface at `0x4000F000`:

| Offset | Register | Description |
|--------|----------|-------------|
| 0x00 | STATUS | 1=running, 2=pass, 3=fail |
| 0x04 | DATA | Test progress data |

```c
#define MCUEMU_TEST_STATUS  (*(volatile uint32_t *)0x4000F000)
#define TEST_STATUS_PASS    0x02

void test_complete(void) {
    MCUEMU_TEST_STATUS = TEST_STATUS_PASS;
}
```

## Future Architectures

The directory structure is designed to support additional architectures:

```
examples/
├── cortex-m/     # ARM Cortex-M (current)
├── riscv/        # RISC-V (planned: ESP32-C3, CH32V)
└── xtensa/       # Xtensa (planned: ESP32)
```

## License

Examples: GPL-2.0-or-later

Vendor SDKs have their own licenses:
- STM32CubeF4: BSD-3-Clause
- FreeRTOS-Kernel: MIT
- NuttX: Apache-2.0
- Zephyr: Apache-2.0
