# Zephyr RTOS Examples for MCUemu

Zephyr RTOS support requires the `west` build tool and CMake.

## Setup

```bash
# Install west
pip3 install west

# Clone Zephyr (already done by setup_repos.sh)
cd ../repos
west init -l zephyr
west update

# Install Python dependencies
pip3 install -r zephyr/scripts/requirements.txt
```

## Building for MCUemu

Zephyr can target STM32F4 Discovery which is compatible with MCUemu's STM32F4 peripheral set.

```bash
cd zephyr
west build -b stm32f4_disco samples/basic/blinky

# The output is at build/zephyr/zephyr.bin
```

## MCUemu Configuration

For Zephyr on STM32F4:
- CPU: Cortex-M4
- Flash: 1MB at 0x08000000
- SRAM: 192KB at 0x20000000
- Peripheral base: 0x40000000

## Running with MCUemu

```bash
# Start peripheral server
python3 python/mcuemu_server.py --port 5555 --soc stm32f4 &

# Start QEMU
./qemu/build/qemu-system-arm \
    -M slab-cortex-m \
    -global slab-cortex-m.cpu-type=cortex-m4 \
    -global slab-cortex-m.flash-size=1048576 \
    -global slab-cortex-m.sram-size=196608 \
    -global slab-cortex-m.tcp-port=5555 \
    -kernel build/zephyr/zephyr.bin \
    -nographic
```

## Status

Zephyr support is documented but not yet fully validated.
The blinky example requires west build infrastructure.
