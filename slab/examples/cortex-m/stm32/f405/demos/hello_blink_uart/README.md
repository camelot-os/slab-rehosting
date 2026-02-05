# HelloBlinkUart - STM32F405 UART Demo

UART-based firmware for MCUemu proxy benchmarking. Unlike HelloBlink which uses USB CDC, this example uses USART2 which is simpler to emulate and doesn't require USB OTG peripheral polling.

## Features

- LED blink on PA13 using TIM2 (500ms period)
- USART2 (115200 8N1) on PA2/PA3
- Sends "helloworld\r\n" on startup
- Echo mode: echoes all received UART data
- MCUemu test interface at 0x4000F000

## Build

```bash
make clean && make
```

Output: `build/HelloBlinkUart.bin` (~7 KB)

## Run with MCUemu

```bash
# TCP proxy mode (from repo root)
PYTHONPATH=slab/python python3 slab/python/slab_cortex_m/mcuemu_server.py --port 5555 &
./build/qemu-system-arm \
    -M slab-cortex-m,cpu-type=cortex-m4,tcp-port=5555 \
    -kernel slab/examples/cortex-m/stm32/f405/demos/hello_blink_uart/build/HelloBlinkUart.bin \
    -nographic

# SHM proxy mode (lower latency)
./build/qemu-system-arm \
    -M slab-cortex-m,proxy-mode=shm,shm-name=/slab_peripheral \
    -kernel slab/examples/cortex-m/stm32/f405/demos/hello_blink_uart/build/HelloBlinkUart.bin \
    -nographic
```

## Peripheral Usage

| Peripheral | Usage |
|------------|-------|
| **RCC** | Clock configuration (HSE + PLL) |
| **GPIO** | PA13 (LED), PA2/PA3 (USART2) |
| **TIM2** | LED blink timer (2 Hz) |
| **USART2** | Serial communication |
| **Flash** | Prefetch enable |
| **PWR** | Voltage scaling |

## Test Protocol

The firmware uses the MCUemu test interface:

| Offset | Register | Description |
|--------|----------|-------------|
| 0x00 | STATUS | 1=running, 2=pass, 3=fail |
| 0x04 | DATA | LED toggle count when pass |

Test passes after 10 LED toggles (~5 seconds).

## Benchmarking

This firmware is ideal for proxy benchmarking because:

1. **No USB OTG** - Avoids complex USB peripheral polling (GRSTCTL)
2. **Deterministic** - Fixed number of peripheral accesses
3. **Fast completion** - Passes in ~5 seconds
4. **Standard peripherals** - RCC, GPIO, TIM, USART are well-supported
