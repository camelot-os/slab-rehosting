# NuttX RTOS Examples for MCUemu

This directory contains NuttX RTOS examples configured for MCUemu testing.

## Prerequisites

```bash
# Clone NuttX (from examples root)
cd ../..
./scripts/setup_repos.sh
```

## Available Configurations

### 1. Hello World

Basic NuttX with NSH shell that prints "Hello, World!".

```bash
./configure.sh stm32f4discovery:hello
make
```

### 2. Blinky

LED blink example using NuttX LED driver.

```bash
./configure.sh stm32f4discovery:blinky
make
```

## Building for MCUemu

NuttX requires some modifications for MCUemu testing:

1. Use simplified UART driver (no DMA)
2. Configure MCUemu test interface peripheral
3. Disable watchdog

### Configuration Options

Add to `.config` or use `make menuconfig`:

```
# MCUemu-specific settings
CONFIG_ARCH_BOARD_CUSTOM=y
CONFIG_ARCH_BOARD_CUSTOM_DIR="$(TOPDIR)/../mcuemu_board"
CONFIG_ARCH_BOARD_CUSTOM_NAME="mcuemu_stm32f4"

# Simplified drivers
CONFIG_STM32_USART1=y
CONFIG_USART1_SERIALDRIVER=y
CONFIG_USART1_RXBUFSIZE=64
CONFIG_USART1_TXBUFSIZE=64

# Disable watchdog
CONFIG_WATCHDOG=n
```

## Running with MCUemu

```bash
# Start peripheral server
python3 ../../python/mcuemu_server.py -c ../../configs/stm32f405.yaml &

# Run QEMU with NuttX
qemu-system-arm -M mcuemu \
    -global mcuemu.cpu-type=cortex-m4 \
    -global mcuemu.tcp-port=5000 \
    -kernel nuttx.bin \
    -nographic

# Access NSH shell via UART
```

## Test Validation

NuttX examples include test hooks that write to the MCUemu test interface:

```c
/* In NuttX app code */
#define MCUEMU_TEST_STATUS  (*(volatile uint32_t *)0x4000F000)
#define TEST_PASS 0x02
#define TEST_FAIL 0x03

void app_main(void)
{
    printf("Hello, World!\n");
    MCUEMU_TEST_STATUS = TEST_PASS;
}
```
