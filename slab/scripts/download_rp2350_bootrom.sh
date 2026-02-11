#!/bin/bash
# Download RP2350 Bootrom A4 binary from official Raspberry Pi release
#
# The bootrom is 32KB ROM at address 0x00000000 containing:
#   - ARM Cortex-M33 secure boot image
#   - ARM Cortex-M23 non-secure boot image (nsboot: USB/UART bootloader)
#   - RISC-V Hazard3 boot image
#
# Usage: bash slab/scripts/download_rp2350_bootrom.sh
#
# Author: Mathieu Renard <mathieu.renard@twistedwires.io>
# Copyright (C) 2026 Twisted Wires Security Lab
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROMS_DIR="${SCRIPT_DIR}/../roms"
BIN_URL="https://github.com/raspberrypi/pico-bootrom-rp2350/releases/download/A4/bootrom-combined.bin"
BIN_FILE="${ROMS_DIR}/rp2350_a4.bin"

mkdir -p "${ROMS_DIR}"

if [ -f "${BIN_FILE}" ]; then
    echo "Bootrom binary already exists: ${BIN_FILE}"
    echo "Size: $(wc -c < "${BIN_FILE}") bytes"
    exit 0
fi

echo "Downloading RP2350 Bootrom A4..."
if command -v wget &>/dev/null; then
    wget -q -O "${BIN_FILE}" "${BIN_URL}"
elif command -v curl &>/dev/null; then
    curl -sL -o "${BIN_FILE}" "${BIN_URL}"
else
    echo "ERROR: Neither wget nor curl found" >&2
    exit 1
fi

SIZE=$(wc -c < "${BIN_FILE}")
echo "Done: ${BIN_FILE} (${SIZE} bytes)"

if [ "${SIZE}" -gt 32768 ]; then
    echo "WARNING: Binary is larger than 32KB ROM size" >&2
fi
