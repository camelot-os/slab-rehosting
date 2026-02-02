#!/bin/bash
# Setup script for STM32H563 TrustZone CDC ACM project
# Clones dependencies and prepares the build environment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPS_DIR="${SCRIPT_DIR}/.."

echo "=== STM32H563 TrustZone CDC ACM - Setup ==="

# Clone STM32CubeH5 if not present
if [ ! -d "${DEPS_DIR}/STM32CubeH5" ]; then
    echo "[1/3] Cloning STM32CubeH5..."
    git clone --depth 1 --recurse-submodules \
        https://github.com/STMicroelectronics/STM32CubeH5.git \
        "${DEPS_DIR}/STM32CubeH5"
else
    echo "[1/3] STM32CubeH5 already present, skipping clone"
fi

# Check for arm-none-eabi-gcc
echo "[2/3] Checking toolchain..."
if ! command -v arm-none-eabi-gcc &> /dev/null; then
    echo "ERROR: arm-none-eabi-gcc not found in PATH"
    echo "Install with:"
    echo "  Ubuntu/Debian: sudo apt install gcc-arm-none-eabi"
    echo "  Arch:          sudo pacman -S arm-none-eabi-gcc"
    echo "  macOS:         brew install arm-none-eabi-gcc"
    exit 1
fi
echo "  Found: $(arm-none-eabi-gcc --version | head -1)"

# Create build directory and configure
echo "[3/3] Configuring CMake build..."
BUILD_DIR="${SCRIPT_DIR}/build"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

cmake -DCMAKE_TOOLCHAIN_FILE="${SCRIPT_DIR}/cmake/arm-none-eabi.cmake" \
      -DSTM32CUBE_H5_PATH="${DEPS_DIR}/STM32CubeH5" \
      "${SCRIPT_DIR}"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Build commands:"
echo "  cd build"
echo "  make secure_fw        # Build secure firmware"
echo "  make nonsecure_fw     # Build non-secure firmware (requires secure_fw first)"
echo "  make all              # Build both"
echo ""
echo "Flash commands (requires STM32CubeProgrammer):"
echo "  make configure_option_bytes  # Set TZEN=1 (once)"
echo "  make flash_secure            # Flash secure FW"
echo "  make flash_nonsecure         # Flash non-secure FW"
echo "  make flash_all               # Flash both"
echo ""
echo "Debug UART: PA9(TX)/PA10(RX) @ 115200 8N1"
echo "USB CDC:    Connect micro-USB to CN1"
