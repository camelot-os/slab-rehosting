# STM32H563 TF-M CDC ACM Demo

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**Author:** Mathieu Renard <mathieu.renard@twistedwires.io>

A Trusted Firmware-M (TF-M) based secure firmware for STM32H563 with USB CDC ACM interface, featuring PSA Certified security services and MCUboot secure boot.

## Build Status

| Component | Status | Size | Description |
|-----------|--------|------|-------------|
| MCUboot Bootloader (BL2) | Built | 169 KB | Secure bootloader with image verification |
| TF-M Secure Firmware | Built | 175 KB | PSA security services |
| TF-M Signed Image | Built | 184 KB | Signed secure image for MCUboot |
| NS Application | Built | 41 KB | ThreadX + USBX + PSA demo |

## Features

- **TF-M Security Services:**
  - PSA Crypto API (AES-256-GCM, SHA-256, ECDSA, ECDH)
  - PSA Protected Storage (encrypted at rest)
  - PSA Internal Trusted Storage
  - PSA Initial Attestation (EAT tokens)

- **Secure Boot (MCUboot/BL2):**
  - RSA-3072 or ECDSA-P256 image signing
  - Rollback protection
  - Dual image update support

- **USB CDC ACM:**
  - Virtual COM port for interactive PSA crypto demo
  - ThreadX RTOS + USBX USB stack
  - Command-line interface for crypto operations

- **ANSSI Compliance:**
  - Stack protection (`-fstack-protector-strong`)
  - Format string security (`-Wformat-security`)
  - Error message sanitization in production mode
  - Approved cryptographic algorithms only

---

## Quick Start

### 1. Prerequisites

```bash
# Ubuntu/Debian
sudo apt install gcc-arm-none-eabi cmake python3-pip

# Python packages
pip install cbor2 cryptography intelhex imgtool jinja2 pyyaml
```

### 2. Clone and Setup

```bash
git clone --recursive https://github.com/user/stm32h563_tfm_cdc.git
cd stm32h563_tfm_cdc

# Initialize submodules (if not cloned with --recursive)
git submodule update --init --recursive
```

### 3. Build TF-M Secure Firmware

```bash
# Create TF-M build directory
mkdir -p build/tfm && cd build/tfm

# Configure TF-M
cmake -DTFM_PLATFORM=stm/stm32h573i_dk \
      -DCMAKE_BUILD_TYPE=Release \
      ../../SDK/tf-m

# Build (this takes several minutes)
make -j$(nproc)

cd ../..
```

### 4. Build Non-Secure Application

```bash
# Create NS build directory
mkdir -p build_ns && cd build_ns

# Configure and build
cmake ..
make -j$(nproc)

cd ..
```

### 5. Flash to Hardware

```bash
# Configure TrustZone option bytes (first time only)
STM32_Programmer_CLI -c port=SWD -ob TZEN=1 SECWM1_PSTRT=0x0 SECWM1_PEND=0x7F

# Flash all images
STM32_Programmer_CLI -c port=SWD -w build/tfm/bin/bl2.bin 0x0C000000 -v
STM32_Programmer_CLI -c port=SWD -w build/tfm/bin/tfm_s_signed.bin 0x0C020000 -v
STM32_Programmer_CLI -c port=SWD -w build_ns/tfm_ns_app.bin 0x08040000 -v
```

### 6. Connect and Use

```bash
# Connect to USB CDC virtual COM port
picocom /dev/ttyACM0 -b 115200

# Or on macOS
screen /dev/tty.usbmodem* 115200
```

---

## USB CDC Command Reference

Once connected via USB, you can interact with the PSA crypto demo using these commands:

### Available Commands

| Command | Description | Example |
|---------|-------------|---------|
| `help` | Show available commands | `help` |
| `status` | Show PSA/TF-M status | `status` |
| `keygen` | Generate AES-256 key | `keygen` |
| `encrypt <text>` | Encrypt text with AES-GCM | `encrypt Hello World` |
| `decrypt <hex>` | Decrypt hex ciphertext | `decrypt 0a1b2c...` |
| `hash <text>` | Compute SHA-256 hash | `hash Hello World` |
| `store <uid> <data>` | Store data in Protected Storage | `store 1 MySecret` |
| `load <uid>` | Load data from Protected Storage | `load 1` |
| `attest` | Get device attestation token | `attest` |
| `random [len]` | Generate random bytes | `random 32` |

### Example Session

```
> status
PSA Status:
  Crypto init: OK
  AES key ID: 0 (none)
  Isolation: Level 1 (SFN)
  Services: Crypto, PS, ITS, Attestation
  Platform: STM32H563 + TF-M v2.1

> keygen
OK: AES-256 key generated (ID: 1)

> encrypt Hello TrustZone!
OK: Encrypted 16 bytes -> 44 bytes (nonce+ct+tag)
Data: 7f3a9b2c...

> hash Hello World
OK: SHA-256 hash (32 bytes)
Data: a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e

> store 100 MySecretData
OK: Stored 12 bytes at UID 100 (encrypted at rest)

> load 100
OK: Loaded 12 bytes from UID 100
Data: MySecretData

> attest
OK: Attestation token (412 bytes, CBOR/EAT format)
Data: d28443a10126a059...
```

---

## Architecture

```
+------------------------------------------------------------------+
|                      BOOT SEQUENCE                                |
+------------------------------------------------------------------+
|  1. Power On -> MCUboot (BL2) @ 0x0C000000                       |
|  2. BL2 verifies TF-M signature (RSA-3072)                       |
|  3. BL2 jumps to TF-M Secure @ 0x0C020000                        |
|  4. TF-M initializes SAU, GTZC, secure services                  |
|  5. TF-M jumps to NS Application @ 0x08040000                    |
+------------------------------------------------------------------+

+------------------------------------------------------------------+
|                    NON-SECURE WORLD                               |
|  +--------------------+  +--------------------+                   |
|  |    USB CDC ACM     |  |    ThreadX RTOS    |                   |
|  |   Command Parser   |  |   Task Scheduler   |                   |
|  +--------------------+  +--------------------+                   |
|              |                                                    |
|              v                                                    |
|  +------------------------------------------------------------+  |
|  |              PSA Crypto Demo Application                    |  |
|  |   keygen | encrypt | decrypt | hash | store | attest        |  |
|  +------------------------------------------------------------+  |
|              | PSA API Calls (psa_*)                              |
|              v                                                    |
+------------------------------------------------------------------+
              | SVC Exception -> Secure World
              v
+------------------------------------------------------------------+
|                    SECURE WORLD (TF-M)                            |
|  +------------------------------------------------------------+  |
|  |            Secure Partition Manager (SPM)                   |  |
|  |         Routes PSA calls to appropriate partition           |  |
|  +------------------------------------------------------------+  |
|       |              |              |              |              |
|  +--------+    +----------+    +--------+    +-----------+        |
|  | Crypto |    | Protected|    |Internal|    |  Initial  |        |
|  |Service |    | Storage  |    |Trusted |    |Attestation|        |
|  |        |    |  (PS)    |    |Storage |    |   (IA)    |        |
|  |AES,SHA,|    |Encrypted |    | (ITS)  |    |EAT Token  |        |
|  |ECC,RSA |    |at Rest   |    |        |    |Generator  |        |
|  +--------+    +----------+    +--------+    +-----------+        |
+------------------------------------------------------------------+
              |
              v
+------------------------------------------------------------------+
|                    BL2 (MCUboot)                                  |
|  +------------------------------------------------------------+  |
|  | Image Verification | Rollback Protection | Firmware Update  |  |
|  +------------------------------------------------------------+  |
+------------------------------------------------------------------+
```

---

## Memory Map

| Region | Start | End | Size | Security | Content |
|--------|-------|-----|------|----------|---------|
| BL2 Flash | 0x0C000000 | 0x0C01FFFF | 128 KB | Secure | MCUboot bootloader |
| TF-M Flash | 0x0C020000 | 0x0C07FFFF | 384 KB | Secure | TF-M + Secure partitions |
| NS Flash | 0x08040000 | 0x081FFFFF | 1.75 MB | Non-Secure | NS Application |
| Secure SRAM | 0x30000000 | 0x3003FFFF | 256 KB | Secure | TF-M runtime data |
| NS SRAM | 0x20040000 | 0x2009FFFF | 384 KB | Non-Secure | ThreadX + App data |

---

## Project Structure

```
stm32h563_tfm_cdc/
├── CMakeLists.txt           # NS application build (top-level)
├── README.md                # This file
├── SDK/
│   ├── STM32CubeH5/         # ST HAL + ThreadX + USBX
│   ├── tf-m/                # Trusted Firmware-M
│   └── mcuboot/             # MCUboot bootloader
├── tfm_config/
│   ├── tfm_build.cmake      # TF-M build configuration
│   └── config_tfm.h         # TF-M feature config
├── app_ns/
│   ├── Inc/
│   │   ├── main.h           # Main header
│   │   ├── psa_crypto_app.h # PSA demo API
│   │   ├── tx_user.h        # ThreadX configuration
│   │   ├── ux_user.h        # USBX configuration
│   │   └── ux_stm32_config.h# USBX STM32 DCD config
│   ├── Src/
│   │   ├── main.c           # Application entry point
│   │   ├── psa_crypto_app.c # PSA API demonstration
│   │   ├── app_usbx_device.c# USBX device initialization
│   │   ├── ux_device_cdc_acm.c    # CDC ACM callbacks
│   │   ├── ux_device_descriptors.c# USB descriptors
│   │   └── stm32h5xx_it.c   # Interrupt handlers
│   └── STM32CubeIDE/
│       └── STM32H563ZITX_FLASH_NS.ld  # Linker script
├── build/
│   └── tfm/                 # TF-M build output
│       └── bin/
│           ├── bl2.bin      # MCUboot bootloader
│           ├── tfm_s.bin    # TF-M secure firmware
│           └── tfm_s_signed.bin  # Signed secure image
└── build_ns/                # NS application build output
    ├── tfm_ns_app.elf       # ELF with debug symbols
    ├── tfm_ns_app.bin       # Binary for flashing
    └── tfm_ns_app.hex       # Intel HEX format
```

---

## Building Details

### TF-M Build Options

```bash
# Debug build with more logging
cmake -DTFM_PLATFORM=stm/stm32h573i_dk \
      -DCMAKE_BUILD_TYPE=Debug \
      -DTFM_ISOLATION_LEVEL=1 \
      ../../SDK/tf-m

# Release build with optimization
cmake -DTFM_PLATFORM=stm/stm32h573i_dk \
      -DCMAKE_BUILD_TYPE=Release \
      -DTFM_ISOLATION_LEVEL=1 \
      ../../SDK/tf-m
```

### NS Application Build Options

```bash
# Custom TF-M path
cmake -DTFM_BUILD_PATH=/path/to/tfm/build ..

# Custom SDK path
cmake -DSTM32CUBE_H5_PATH=/path/to/STM32CubeH5 ..
```

### Compiler Security Flags (ANSSI Compliance)

The build automatically enables these security flags:

| Flag | Purpose |
|------|---------|
| `-fstack-protector-strong` | Stack buffer overflow detection |
| `-Wformat -Wformat-security` | Format string vulnerability warnings |
| `-fno-common` | Detect multiple definitions |
| `-fdata-sections -ffunction-sections` | Dead code elimination |

---

## PSA API Usage Examples

### Key Generation and Encryption

```c
#include "psa/crypto.h"

// Initialize PSA (connects to TF-M crypto service)
psa_status_t status = psa_crypto_init();

// Generate AES-256 key (key stays in secure world)
psa_key_attributes_t attr = PSA_KEY_ATTRIBUTES_INIT;
psa_set_key_usage_flags(&attr, PSA_KEY_USAGE_ENCRYPT | PSA_KEY_USAGE_DECRYPT);
psa_set_key_algorithm(&attr, PSA_ALG_GCM);
psa_set_key_type(&attr, PSA_KEY_TYPE_AES);
psa_set_key_bits(&attr, 256);

psa_key_id_t key_id;
status = psa_generate_key(&attr, &key_id);  // Returns handle, not key material!

// Encrypt with AES-GCM
uint8_t nonce[12], ciphertext[128];
size_t ct_len;
psa_generate_random(nonce, sizeof(nonce));
status = psa_aead_encrypt(key_id, PSA_ALG_GCM,
                          nonce, sizeof(nonce),
                          NULL, 0,  // No additional data
                          plaintext, plaintext_len,
                          ciphertext, sizeof(ciphertext), &ct_len);
```

### Protected Storage

```c
#include "psa/protected_storage.h"

// Store sensitive data (encrypted at rest by TF-M)
psa_storage_uid_t uid = 0x12345678;
status = psa_ps_set(uid, data_len, data, PSA_STORAGE_FLAG_NONE);

// Retrieve data
size_t read_len;
status = psa_ps_get(uid, 0, buffer_size, buffer, &read_len);

// Delete when no longer needed
status = psa_ps_remove(uid);
```

### Device Attestation

```c
#include "psa/initial_attestation.h"

// Get attestation token (signed by device's attestation key)
uint8_t challenge[32], token[512];
size_t token_len;

psa_generate_random(challenge, sizeof(challenge));
status = psa_initial_attest_get_token(challenge, sizeof(challenge),
                                       token, sizeof(token), &token_len);
// Token is in CBOR/EAT format, can be verified by attestation server
```

---

## Security Considerations

### Development vs Production

| Aspect | Development | Production |
|--------|-------------|------------|
| Signing keys | Demo keys in repo | HSM-stored keys |
| Error messages | Detailed (status codes) | Sanitized |
| Debug interface | SWD enabled | SWD locked (RDP2) |
| PRODUCTION_MODE | 0 | 1 |

### Generating Production Keys

```bash
# RSA-3072 (recommended for compatibility)
openssl genrsa -out production-rsa-3072.pem 3072

# ECDSA P-256 (smaller, faster)
openssl ecparam -genkey -name prime256v1 -out production-ec-p256.pem

# Store keys securely - NEVER commit to version control!
```

### Enabling Production Mode

In `app_ns/Src/psa_crypto_app.c`:
```c
#define PRODUCTION_MODE  1  // Sanitizes error messages
```

### Hardware Security

```bash
# Lock debug interface (IRREVERSIBLE on RDP Level 2!)
STM32_Programmer_CLI -c port=SWD -ob RDP=0xCC  # Level 2 - permanent lock
```

---

## Troubleshooting

### Build Issues

| Problem | Solution |
|---------|----------|
| `TF-M build not found` | Build TF-M first: `cd build/tfm && make` |
| `arm-none-eabi-gcc not found` | Install: `apt install gcc-arm-none-eabi` |
| `Python package missing` | `pip install cbor2 cryptography intelhex imgtool` |
| GCC internal compiler error | Applied workaround in TF-M platform CMakeLists.txt |

### Runtime Issues

| Problem | Solution |
|---------|----------|
| USB not recognized | Check USB cable, try different port |
| `PSA_ERROR_NOT_PERMITTED` | Key usage flags don't match operation |
| `PSA_ERROR_NOT_SUPPORTED` | Service not enabled in TF-M config |
| No response from device | Check TrustZone option bytes are configured |

### Flash Issues

| Problem | Solution |
|---------|----------|
| `TZEN not set` | Run: `STM32_Programmer_CLI -c port=SWD -ob TZEN=1` |
| `Image verification failed` | Ensure image is properly signed |
| `Secure fault on boot` | Check memory regions match linker script |

---

## License

This project is licensed under the **Apache License 2.0** - see the [LICENSE](LICENSE) file for details.

**Third-party components** (see [NOTICE](NOTICE) for full attribution):
- **TF-M:** BSD-3-Clause (ARM Limited)
- **MCUboot:** Apache-2.0 (Linaro/JUUL Labs)
- **ThreadX/USBX:** Microsoft Azure RTOS License (requires STM32H5 hardware)
- **STM32 HAL/CMSIS:** ST SLA0044 (requires STMicroelectronics hardware)

**Hardware Requirement:** The Azure RTOS and ST library licenses require this software to be used exclusively with STMicroelectronics microcontrollers. STM32H5 is explicitly listed as Licensed Hardware.

```
Copyright 2024-2026 Mathieu Renard <mathieu.renard@twistedwires.io>

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

---

## References

- [TF-M User Guide](https://tf-m-user-guide.trustedfirmware.org/)
- [PSA Certified APIs](https://arm-software.github.io/psa-api/)
- [MCUboot Documentation](https://docs.mcuboot.com/)
- [STM32H5 Reference Manual](https://www.st.com/resource/en/reference_manual/rm0481.pdf)
- [ANSSI Secure Development Guide](https://www.ssi.gouv.fr/guide/regles-de-programmation-pour-le-developpement-securise-de-logiciels-en-langage-c/)
