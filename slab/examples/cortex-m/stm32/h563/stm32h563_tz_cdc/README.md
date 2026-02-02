# STM32H563 TrustZone CDC ACM Demo

A bare-metal TrustZone demonstration for STM32H563 with USB CDC ACM interface, featuring secure/non-secure world separation and NSC (Non-Secure Callable) gateway functions.

## Features

- **TrustZone Security:**
  - SAU (Security Attribution Unit) configuration
  - GTZC (Global TrustZone Controller) peripheral security
  - MPCBB (Memory Protection Controller Block-Based) for SRAM
  - NSC gateway for secure function calls

- **USB CDC ACM:**
  - Virtual COM port over USB
  - ThreadX RTOS + USBX stack
  - Debug UART fallback

- **Secure Services:**
  - AES-256-GCM encryption/decryption
  - SHA-256 hashing
  - True Random Number Generator
  - Secure LED control

- **ANSSI Compliance:**
  - Compiler hardening flags
  - Input validation on NSC functions
  - Watchdog configuration
  - Debug lockout (production mode)

## Quick Start

```bash
# 1. Clone with submodules
git clone --recursive https://github.com/user/stm32h563_tz_cdc.git
cd stm32h563_tz_cdc

# 2. Build
make

# 3. Configure TrustZone (first time only)
make configure_tz

# 4. Flash
make flash_all

# 5. Connect terminal
picocom /dev/ttyACM0 -b 115200
```

## Prerequisites

- **Toolchain:** `arm-none-eabi-gcc` (12.x recommended)
  ```bash
  # Ubuntu/Debian
  sudo apt install gcc-arm-none-eabi

  # Arch Linux
  sudo pacman -S arm-none-eabi-gcc

  # macOS
  brew install arm-none-eabi-gcc
  ```

- **CMake:** Version 3.22 or later

- **STM32CubeProgrammer:** For flashing
  - Download from [ST website](https://www.st.com/en/development-tools/stm32cubeprog.html)

## Building

```bash
# Initialize SDK submodule (first time)
make setup

# Build both firmware images
make

# Clean build
make clean
```

## Flashing

### First Time Setup

Configure TrustZone option bytes:

```bash
make configure_tz
```

### Flash Firmware

```bash
# Flash both images
make flash_all

# Or individually
make flash_secure      # Secure firmware to 0x0C000000
make flash_nonsecure   # Non-Secure firmware to 0x08040000
```

### Manual Flash Commands

```bash
# Secure firmware
STM32_Programmer_CLI -c port=SWD -w build/secure_fw.bin 0x0C000000 -v

# Non-Secure firmware
STM32_Programmer_CLI -c port=SWD -w build/nonsecure_fw.bin 0x08040000 -v

# Read option bytes
STM32_Programmer_CLI -c port=SWD -ob displ

# Configure TrustZone
STM32_Programmer_CLI -c port=SWD -ob TZEN=1 SECWM_PSTRT=0x0 SECWM_PEND=0x3F
```

## Boot Process

The STM32H563 with TrustZone follows a secure boot chain where the CPU always starts in Secure state:

```
                              POWER ON / RESET
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                           SECURE WORLD                                      │
│                    (CPU always starts here)                                 │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 1. SAU_Setup() - Security Attribution Unit                          │   │
│  │    ┌────────────────────────────────────────────────────────────┐   │   │
│  │    │ Region 0: 0x08040000-0x081FFFFF │ Non-Secure  │ NS Flash   │   │   │
│  │    │ Region 1: 0x0C038000-0x0C03FFFF │ NSC         │ Veneers    │   │   │
│  │    │ Region 2: 0x20040000-0x200BFFFF │ Non-Secure  │ NS SRAM    │   │   │
│  │    │ Region 3: 0x40000000-0x4FFFFFFF │ Non-Secure  │ NS Periph  │   │   │
│  │    └────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 2. HAL_Init() + SystemClock_Config()                                │   │
│  │    • Configure PLL: HSE 8MHz → 250MHz SYSCLK                        │   │
│  │    • Enable HSI48 for USB (48 MHz)                                  │   │
│  │    • Configure SysTick                                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 3. MX_GTZC_S_Init() - Global TrustZone Controller                   │   │
│  │    • MPCBB: SRAM1 (256KB) → Secure, SRAM2 (384KB) → Non-Secure      │   │
│  │    • TZSC: USB_OTG_FS → Non-Secure, USART1 → Secure                 │   │
│  │    • GPDMA1/GPDMA2 → Non-Secure (for USB DMA)                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 4. MX_IWDG_Init() - Watchdog (if SECURITY_ENABLE_IWDG)              │   │
│  │    • 4 second timeout                                               │   │
│  │    • Must be refreshed by NS application                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 5. NonSecure_Init() - Jump to Non-Secure World                      │   │
│  │    • Validate NS image (stack pointer, reset handler in range)      │   │
│  │    • Set SCB_NS->VTOR = 0x08042000                                  │   │
│  │    • Read NS stack pointer from 0x08042000                          │   │
│  │    • Read NS Reset_Handler from 0x08042004                          │   │
│  │    • __TZ_set_MSP_NS(ns_stack_ptr)                                  │   │
│  │    • Jump to NS Reset_Handler ─────────────────────────────────┐    │   │
│  └────────────────────────────────────────────────────────────────│────┘   │
│                                                                   │        │
└───────────────────────────────────────────────────────────────────│────────┘
                                                                    │
                    ┌───────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                          NON-SECURE WORLD                                   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 6. Reset_Handler (startup_stm32h563xx.s)                            │   │
│  │    • Copy .data from Flash to RAM                                   │   │
│  │    • Zero .bss section                                              │   │
│  │    • Call SystemInit() then main()                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 7. main() → tx_kernel_enter()                                       │   │
│  │    • ThreadX RTOS initialization                                    │   │
│  │    • Create app thread (USB + CDC ACM)                              │   │
│  │    • Scheduler starts running threads                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 8. USB CDC ACM Enumeration                                          │   │
│  │    • USBX device stack initialization                               │   │
│  │    • Device descriptor sent to host                                 │   │
│  │    • Host loads CDC ACM driver → /dev/ttyACM0                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 9. Application Loop                                                 │   │
│  │    • Receive commands via USB CDC                                   │   │
│  │    • Call NSC functions for crypto operations                       │   │
│  │    • Send responses back to host                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### TrustZone Key Concepts

| Component | Description |
|-----------|-------------|
| **SAU** | Security Attribution Unit - defines memory region security at CPU level |
| **IDAU** | Implementation Defined Attribution Unit - hardware security (option bytes) |
| **GTZC** | Global TrustZone Controller - peripheral and SRAM security |
| **MPCBB** | Memory Protection Controller Block-Based - 256-byte SRAM granularity |
| **TZSC** | TrustZone Security Controller - peripheral access control |
| **NSC** | Non-Secure Callable - gateway region for S↔NS transitions |

### NSC Function Call Flow

```
 Non-Secure Code                    NSC Region                     Secure Code
       │                               │                                │
       │  SECURE_AES_Encrypt(...)      │                                │
       ├──────────────────────────────▶│                                │
       │                               │  SG instruction (gateway)      │
       │                               ├───────────────────────────────▶│
       │                               │                                │
       │                               │  • Validate input pointers     │
       │                               │  • Check buffer bounds         │
       │                               │  • Perform AES encryption      │
       │                               │  • Copy result to NS buffer    │
       │                               │                                │
       │                               │◀───────────────────────────────┤
       │                               │  BXNS lr (return to NS)        │
       │◀──────────────────────────────┤                                │
       │  return value                 │                                │
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Non-Secure World                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │    App      │  │  USB CDC    │  │      ThreadX        │  │
│  │   Logic     │◄─┤   (USBX)    │  │       RTOS          │  │
│  └──────┬──────┘  └─────────────┘  └─────────────────────┘  │
│         │                                                    │
│         │ NSC Calls                                          │
└─────────┼────────────────────────────────────────────────────┘
          │
┌─────────▼────────────────────────────────────────────────────┐
│                     Secure World                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              NSC Gateway Functions                       │ │
│  │  SECURE_AES_Encrypt()    SECURE_AES_Decrypt()           │ │
│  │  SECURE_SHA256_Hash()    SECURE_RNG_Generate()          │ │
│  │  SECURE_LED_On/Off()                                     │ │
│  └─────────────────────────────────────────────────────────┘ │
│                              │                               │
│  ┌──────────────┐  ┌─────────▼──────────┐  ┌──────────────┐ │
│  │    SAU       │  │   Crypto Engine    │  │    GTZC      │ │
│  │ Configuration│  │   AES, SHA, RNG    │  │ Peripheral   │ │
│  └──────────────┘  └────────────────────┘  └──────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

## NSC API Reference

### Cryptographic Functions

```c
// AES-256-GCM Encryption
int32_t SECURE_AES_Encrypt(
    const uint8_t *plaintext, uint32_t len,
    const uint8_t *key,       // 32 bytes
    const uint8_t *iv,        // 12 bytes
    uint8_t *ciphertext,
    uint8_t *tag              // 16 bytes
);

// AES-256-GCM Decryption
int32_t SECURE_AES_Decrypt(
    const uint8_t *ciphertext, uint32_t len,
    const uint8_t *key,
    const uint8_t *iv,
    const uint8_t *tag,
    uint8_t *plaintext
);

// SHA-256 Hash
int32_t SECURE_SHA256_Hash(
    const uint8_t *data, uint32_t len,
    uint8_t *hash             // 32 bytes output
);

// Random Number Generation
int32_t SECURE_RNG_Generate(
    uint8_t *buffer, uint32_t len
);
```

### Utility Functions

```c
// LED Control
void SECURE_LED_On(void);
void SECURE_LED_Off(void);
void SECURE_LED_Toggle(void);

// Device ID
int32_t SECURE_GetDeviceID(uint32_t *id, uint32_t len);
```

## Memory Map

| Region | Start | End | Size | Security |
|--------|-------|-----|------|----------|
| Secure Flash | 0x0C000000 | 0x0C03FFFF | 256KB | Secure |
| NS Flash | 0x08040000 | 0x081FFFFF | 1.75MB | Non-Secure |
| SRAM1 | 0x30000000 | 0x3003FFFF | 256KB | Secure |
| SRAM2 | 0x20040000 | 0x2009FFFF | 384KB | Non-Secure |
| Peripherals | Various | - | - | Per GTZC config |

## Project Structure

```
stm32h563_tz_cdc/
├── Makefile                 # Build automation
├── CMakeLists.txt           # CMake configuration
├── README.md                # This file
├── SDK/
│   └── STM32CubeH5/         # SDK submodule
├── Secure/
│   ├── Inc/
│   │   ├── main.h
│   │   ├── stm32h5xx_hal_conf.h
│   │   ├── partition_stm32h563xx.h
│   │   └── security_config.h
│   ├── Src/
│   │   ├── main.c           # Secure entry, TZ setup
│   │   ├── secure_nsc.c     # NSC gateway functions
│   │   └── system_stm32h5xx_s.c
│   └── STM32CubeIDE/
│       └── STM32H563ZITX_FLASH_S.ld
├── Secure_nsclib/
│   └── secure_nsc.h         # NSC function prototypes
├── NonSecure/
│   ├── Inc/
│   │   ├── main.h
│   │   └── stm32h5xx_hal_conf.h
│   ├── Src/
│   │   ├── main.c           # ThreadX + USB init
│   │   └── app_usbx_device.c
│   └── STM32CubeIDE/
│       └── STM32H563ZITX_FLASH_NS.ld
├── docs/                    # Sphinx documentation
│   ├── conf.py
│   ├── index.rst
│   ├── security/
│   ├── architecture/
│   └── diagrams/
└── cmake/
    └── arm-none-eabi.cmake
```

## Documentation

Build the Sphinx documentation:

```bash
make docs
# Open docs/_build/html/index.html
```

## Security Considerations

This project implements ANSSI security recommendations:

- **Compiler Hardening:** Stack protection, format security
- **Input Validation:** All NSC parameters validated
- **Memory Isolation:** SAU + MPCBB configuration
- **Watchdog:** IWDG enabled in production
- **Debug Lockout:** SWD disabled in production mode

See `docs/security/anssi_compliance.rst` for full compliance checklist.

## Troubleshooting

### Build Issues

**SDK not found:** Run `make setup` to initialize submodule

**Compiler not found:** Ensure `arm-none-eabi-gcc` is in PATH

### Flash Issues

**Device not found:** Check ST-LINK connection with `STM32_Programmer_CLI -c port=SWD`

**TrustZone not enabled:** Run `make configure_tz` first

### USB Issues

**No /dev/ttyACM0:** Check both firmware images are flashed

## License

MIT License

## References

- [STM32H563 Reference Manual (RM0481)](https://www.st.com/resource/en/reference_manual/rm0481.pdf)
- [STM32H5 TrustZone Application Note (AN5347)](https://www.st.com/resource/en/application_note/an5347.pdf)
- [ANSSI Embedded Security Guidelines](https://www.ssi.gouv.fr/)
