#!/bin/bash
# Download RP2040 Bootrom B2 binary from official Raspberry Pi release
#
# The bootrom is 16KB ROM at address 0x00000000 that enters USB boot mode
# when no valid flash image is found.
#
# Usage: bash slab/scripts/download_rp2040_bootrom.sh
#
# Author: Mathieu Renard <mathieu.renard@twistedwires.io>
# Copyright (C) 2026 Twisted Wires Security Lab
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROMS_DIR="${SCRIPT_DIR}/../roms"
ELF_URL="https://github.com/raspberrypi/pico-bootrom-rp2040/releases/download/b2/b2.elf"
ELF_FILE="${ROMS_DIR}/rp2040_b2.elf"
BIN_FILE="${ROMS_DIR}/rp2040_b2.bin"

mkdir -p "${ROMS_DIR}"

if [ -f "${BIN_FILE}" ]; then
    echo "Bootrom binary already exists: ${BIN_FILE}"
    echo "Size: $(wc -c < "${BIN_FILE}") bytes"
    exit 0
fi

echo "Downloading RP2040 Bootrom B2..."
if command -v wget &>/dev/null; then
    wget -q -O "${ELF_FILE}" "${ELF_URL}"
elif command -v curl &>/dev/null; then
    curl -sL -o "${ELF_FILE}" "${ELF_URL}"
else
    echo "ERROR: Neither wget nor curl found" >&2
    exit 1
fi

echo "Extracting raw binary..."
if command -v arm-none-eabi-objcopy &>/dev/null; then
    arm-none-eabi-objcopy -O binary "${ELF_FILE}" "${BIN_FILE}"
elif command -v llvm-objcopy &>/dev/null; then
    llvm-objcopy -O binary "${ELF_FILE}" "${BIN_FILE}"
else
    echo "ERROR: Neither arm-none-eabi-objcopy nor llvm-objcopy found" >&2
    echo "Install arm-none-eabi-gcc or llvm toolchain" >&2
    rm -f "${ELF_FILE}"
    exit 1
fi

rm -f "${ELF_FILE}"

SIZE=$(wc -c < "${BIN_FILE}")
echo "Done: ${BIN_FILE} (${SIZE} bytes)"

if [ "${SIZE}" -gt 16384 ]; then
    echo "WARNING: Binary is larger than 16KB ROM size" >&2
fi
