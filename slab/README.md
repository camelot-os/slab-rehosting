# SLAB Cortex-M: Modular MCU Emulation Platform

**SLAB** (Security Lab) Cortex-M is a QEMU-based platform for ARM Cortex-M firmware emulation with Python peripheral control. It enables firmware testing, security research, and peripheral prototyping without custom QEMU recompilation.

Copyright (C) 2026 TwistedWires Security Lab. All Rights Reserved.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     QEMU slab-cortex-m Machine                          │
│                                                                         │
│  ┌──────────────────┐  ┌───────────┐  ┌───────────┐  ┌──────────────┐ │
│  │  ARM Cortex-M    │  │   Flash   │  │   SRAM    │  │   NVIC/MPU   │ │
│  │  M0+ → M85       │  │  (≤2MB)   │  │  (≤512KB) │  │  TrustZone   │ │
│  └────────┬─────────┘  └───────────┘  └───────────┘  └──────────────┘ │
│           │                                                             │
│           │  Peripheral access: 0x40000000 - 0x5FFFFFFF                │
│           ▼                                                             │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              Peripheral Proxy (TCP:5555 or POSIX SHM)           │   │
│  └───────────────────────────────┬─────────────────────────────────┘   │
└──────────────────────────────────┼─────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Python Peripheral Server                            │
│                                                                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │
│  │   RCC   │  │  GPIO   │  │  USART  │  │   SPI   │  │   USB OTG   │  │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └──────┬──────┘  │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐         │         │
│  │  CRYP   │  │  HASH   │  │   DMA   │  │  Timer  │  ┌──────▼──────┐  │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘  │ USBIP Server│  │
│                                                       │ (port 3240) │  │
│                                                       └──────┬──────┘  │
└──────────────────────────────────────────────────────────────┼─────────┘
                                                               │
                                                    ┌──────────▼──────────┐
                                                    │  Host: /dev/ttyACM0 │
                                                    │  pyserial, lsusb    │
                                                    └─────────────────────┘
```

---

## Quick Start

### 1. Build QEMU

```bash
mkdir -p build && cd build
../configure --target-list=arm-softmmu --enable-debug
ninja
cd ..

# Verify
./build/qemu-system-arm -M help | grep slab
# slab-cortex-m   Slab Cortex-M - Generic ARM Cortex-M with peripheral export
```

### 2. Run Example Firmware

**Terminal 1: Start Peripheral Server**

```bash
PYTHONPATH=slab/python python3 slab/python/slab_cortex_m/mcuemu_server.py --port 5555
```

**Terminal 2: Run QEMU**

```bash
./build/qemu-system-arm \
    -M slab-cortex-m,cpu-type=cortex-m4,tcp-port=5555 \
    -kernel slab/examples/cortex-m/stm32/f405/demos/hello_blink_uart/build/HelloBlinkUart.bin \
    -nographic
```

---

## Example Firmwares

### STM32F405 USB CDC ACM

A USB CDC-ACM (virtual serial port) device that accepts commands and responds:

```
examples/cortex-m/stm32/f439/usb/crypto_cdc/
├── main.c                  # Firmware source
├── stm32_crypto_cdc.bin    # Pre-built binary
├── test_e2e_crypto.py      # End-to-end test
└── Makefile
```

**Features:**
- USB CDC-ACM enumeration via USBIP
- PING/PONG command handling
- AES-128/256 encryption commands
- SHA-256 hash computation

**Run the test:**

```bash
# Start emulation with USB
python3 tests/firmware/examples/stm32_crypto_cdc/test_e2e_crypto.py
```

### STM32H563 TrustZone

A dual-world TrustZone application with Secure and Non-Secure firmware:

```
examples/cortex-m/stm32/h563/stm32h563_tz_cdc/
├── Secure/                 # Secure world firmware
│   └── Src/main.c          # SAU, clock, UART init
├── NonSecure/              # Non-Secure world firmware
│   └── Src/main.c          # ThreadX RTOS, USB CDC
├── Secure_nsclib/          # NSC (Non-Secure Callable) library
├── build/
│   ├── secure_fw.bin       # Secure firmware (0x0C000000)
│   └── nonsecure_fw.bin    # Non-Secure firmware (0x08042000)
└── README.md
```

**Features:**
- ARMv8-M TrustZone with SAU configuration
- Secure ↔ Non-Secure transitions via NSC
- ThreadX RTOS in Non-Secure world
- USB CDC over TrustZone boundary

**Run the emulation:**

```bash
./build/qemu-system-arm \
    -M slab-cortex-m,cpu-type=cortex-m33,flash-base=0x0C000000,sram-base=0x30000000,sram-size=0xa0000,trustzone=on \
    -kernel slab/examples/cortex-m/stm32/h563/stm32h563_tz_cdc/build/secure_fw.bin \
    -device loader,file=slab/examples/cortex-m/stm32/h563/stm32h563_tz_cdc/build/nonsecure_fw.bin,addr=0x08042000 \
    -nographic
```

---

## Documentation

Full documentation is available in Sphinx format:

```bash
cd docs
pip install sphinx furo myst-parser sphinx-copybutton
make html
# Open docs/build/html/index.html
```

### Documentation Contents

| Section | Description |
|---------|-------------|
| **Quickstart** | Installation and first emulation |
| **Tutorials** | Step-by-step guides for firmware emulation |
| **Stubbing Peripherals** | Create custom peripheral stubs |
| **UI Peripherals** | Build LED displays and consoles |
| **Debugging Bootloops** | Fix common boot issues |
| **TrustZone Emulation** | Secure/Non-Secure firmware |
| **API Reference** | Full Python API documentation |

---

## Python Packages

| Package | Description |
|---------|-------------|
| `slab_cortex_m` | Core emulation: TCP/SHM bridge, USB OTG, CDC |
| `slab_stm32` | STM32 peripheral library (F0/F1/F4/H7/L4/U5/WB) |
| `slab_nrf` | Nordic nRF52840/nRF5340 peripherals |
| `slab_nxp` | NXP LPC55S69 / i.MX RT1060 peripherals |
| `slab_rp2040` | RP2040/RP2350 peripherals + PIO |
| `slab_gui` | Debug dashboard, logic analyzer, LED display |
| `slab_mcp` | MCP server for AI-assisted analysis |

---

## Supported MCUs

| Vendor | MCU Family | CPU Core | Features |
|--------|------------|----------|----------|
| STMicro | STM32F0 | Cortex-M0 | Basic GPIO, UART, SPI |
| STMicro | STM32F1 | Cortex-M3 | USB OTG FS |
| STMicro | STM32F4 | Cortex-M4 | DSP, FPU, CRYP, HASH, USB OTG |
| STMicro | STM32H7 | Cortex-M7 + M4 | Dual-core, DMA2D |
| STMicro | STM32H5 | Cortex-M33 | TrustZone, ThreadX |
| STMicro | STM32L4 | Cortex-M4 | Low power, USB |
| STMicro | STM32U5 | Cortex-M33 | TrustZone, OTFDEC |
| Nordic | nRF52840 | Cortex-M4 | BLE, USB, QSPI |
| Nordic | nRF5340 | Cortex-M33 + M33 | Dual-core, TrustZone |
| NXP | LPC55S69 | Cortex-M33 | TrustZone, PUF, CASPER |
| NXP | i.MX RT1060 | Cortex-M7 | High speed, FlexSPI |
| RaspberryPi | RP2040 | Cortex-M0+ × 2 | Dual-core, PIO |
| RaspberryPi | RP2350 | Cortex-M33 × 2 | TrustZone, Hazard3 RISC-V |

---

## Debug Dashboard

MCUemu includes a professional debug dashboard:

```bash
python3 /tmp/test_dashboard_pro.py
```

**Features:**
- **Start/Stop/Reset Controls**: Interactive emulator control
- **Logic Analyzer**: Real-time waveforms with zoom/pan
- **Dual Console**: UART and USB CDC with input fields
- **LED Status**: GPIO state visualization
- **Export**: VCD and Sigrok-compatible captures

**Keyboard Shortcuts:**
| Key | Action |
|-----|--------|
| Space | Start/Stop emulation |
| R | Reset emulation |
| E | Export capture |
| +/- | Zoom in/out |
| ←/→ | Scroll waveforms |
| A | Toggle auto-scroll |
| Esc | Quit |

---

## Testing

```bash
# Run unit tests
PYTHONPATH=slab/python pytest slab/tests/ -v

# Run specific test suites
pytest tests/test_svd_parser.py -v        # SVD parsing
pytest tests/test_bootrom.py -v           # RP2040/RP2350 bootrom
pytest tests/test_usbip_cdc.py -v         # USB-IP CDC-ACM
pytest python/slab_stm32/test_f439_crypto.py -v  # CRYP/HASH

# Run end-to-end tests (requires QEMU)
python3 tests/firmware/examples/stm32_crypto_cdc/test_e2e_crypto.py
```

---

## License

- **QEMU Machine Code** (`qemu/hw/`): GPL-3.0-or-later
- **Python Packages and Tests**: Apache-2.0

---

## Author

**Mathieu Renard**
TwistedWires Security Lab
<mathieu.renard@twistedwires.io>

---

## References

1. ARM Cortex-M Technical Reference Manuals
2. STM32 Reference Manuals (RM0090, RM0468, RM0481)
3. CMSIS-SVD Schema Specification
4. USB 2.0 Specification
5. DWC2 OTG Controller Databook (Synopsys)
6. USBIP Protocol Specification

---

Copyright (C) 2026 TwistedWires Security Lab. All Rights Reserved.
