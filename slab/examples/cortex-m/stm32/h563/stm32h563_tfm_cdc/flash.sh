#!/bin/bash
# Flash TF-M secure firmware + NS application to STM32H563
# Requires: STM32CubeProgrammer (STM32_Programmer_CLI in PATH)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TFM_BIN="${SCRIPT_DIR}/deps/trusted-firmware-m/build_spe/install/bin/tfm_s.bin"
NS_BIN="${SCRIPT_DIR}/build_ns/tfm_ns_app.bin"

echo "=== Flashing STM32H563 TF-M + CDC ACM ==="

# Check binaries exist
if [ ! -f "${TFM_BIN}" ]; then
    echo "ERROR: TF-M secure binary not found: ${TFM_BIN}"
    echo "Run ./setup.sh first"
    exit 1
fi

if [ ! -f "${NS_BIN}" ]; then
    echo "ERROR: NS application binary not found: ${NS_BIN}"
    echo "Run: cd build_ns && make"
    exit 1
fi

# Check programmer
if ! command -v STM32_Programmer_CLI &> /dev/null; then
    echo "ERROR: STM32_Programmer_CLI not found"
    echo "Install STM32CubeProgrammer from: https://www.st.com/en/development-tools/stm32cubeprog.html"
    exit 1
fi

echo ""
echo "[1/3] Configuring Option Bytes (TZEN=1)..."
STM32_Programmer_CLI -c port=SWD mode=HotPlug \
    -ob TZEN=1 SECWM_PSTRT=0x0 SECWM_PEND=0x7F \
    || echo "  Warning: Option bytes may already be set"

echo ""
echo "[2/3] Flashing TF-M Secure firmware (0x0C000000)..."
STM32_Programmer_CLI -c port=SWD mode=HotPlug \
    -w "${TFM_BIN}" 0x0C000000 -v

echo ""
echo "[3/3] Flashing Non-Secure application (0x08042000)..."
STM32_Programmer_CLI -c port=SWD mode=HotPlug \
    -w "${NS_BIN}" 0x08042000 -v

echo ""
echo "=== Flash complete ==="
echo ""
echo "Connect UART1 (PA9 TX) at 115200 for TF-M debug output"
echo "Connect USB (CN1) for CDC ACM virtual COM port"
echo ""
echo "Available commands over USB CDC:"
echo "  keygen          - Generate AES-256 key"
echo "  encrypt <text>  - AES-GCM encrypt"
echo "  decrypt <hex>   - AES-GCM decrypt"
echo "  hash <text>     - SHA-256 hash"
echo "  store <k> <v>   - Protected Storage write"
echo "  load <k>        - Protected Storage read"
echo "  attest          - Get attestation token"
echo "  status          - Show PSA status"
