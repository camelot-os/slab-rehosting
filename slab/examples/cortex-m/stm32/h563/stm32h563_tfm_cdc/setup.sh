#!/bin/bash
# Setup script for STM32H563 TF-M CDC ACM project
# Clones TF-M and STM32CubeH5, builds the Secure Processing Environment (SPE)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPS_DIR="${SCRIPT_DIR}/deps"

echo "=== STM32H563 TF-M CDC ACM - Setup ==="
echo ""

# ---- Check toolchain ----
echo "[1/5] Checking toolchain..."
if ! command -v arm-none-eabi-gcc &> /dev/null; then
    echo "ERROR: arm-none-eabi-gcc not found"
    echo "Install: sudo apt install gcc-arm-none-eabi"
    exit 1
fi
if ! command -v cmake &> /dev/null; then
    echo "ERROR: cmake not found"
    echo "Install: sudo apt install cmake"
    exit 1
fi
echo "  GCC: $(arm-none-eabi-gcc --version | head -1)"
echo "  CMake: $(cmake --version | head -1)"

# ---- Clone dependencies ----
mkdir -p "${DEPS_DIR}"

echo "[2/5] Cloning TF-M..."
if [ ! -d "${DEPS_DIR}/trusted-firmware-m" ]; then
    git clone --depth 1 --branch TF-Mv2.1.0 \
        https://git.trustedfirmware.org/TF-M/trusted-firmware-m.git \
        "${DEPS_DIR}/trusted-firmware-m"
else
    echo "  Already present, skipping"
fi

echo "[3/5] Cloning STM32CubeH5..."
if [ ! -d "${DEPS_DIR}/STM32CubeH5" ]; then
    git clone --depth 1 --recurse-submodules \
        https://github.com/STMicroelectronics/STM32CubeH5.git \
        "${DEPS_DIR}/STM32CubeH5"
else
    echo "  Already present, skipping"
fi

# ---- Build TF-M (Secure Processing Environment) ----
echo "[4/5] Building TF-M Secure firmware..."
TFM_SRC="${DEPS_DIR}/trusted-firmware-m"
TFM_BUILD="${TFM_SRC}/build_spe"

if [ ! -f "${TFM_BUILD}/install/interface/include/psa/crypto.h" ]; then
    cmake -S "${TFM_SRC}" -B "${TFM_BUILD}" \
        -C "${SCRIPT_DIR}/tfm_config/tfm_build.cmake"

    cmake --build "${TFM_BUILD}" -- -j$(nproc) install

    echo "  TF-M built successfully"
    echo "  Secure binary: ${TFM_BUILD}/install/bin/tfm_s.bin"
    echo "  PSA headers:   ${TFM_BUILD}/install/interface/include/psa/"
    echo "  NS interface:  ${TFM_BUILD}/install/interface/lib/"
else
    echo "  TF-M already built, skipping"
fi

# ---- Configure NS application ----
echo "[5/5] Configuring Non-Secure application..."
NS_BUILD="${SCRIPT_DIR}/build_ns"
mkdir -p "${NS_BUILD}"

cmake -S "${SCRIPT_DIR}" -B "${NS_BUILD}" \
    -DCMAKE_TOOLCHAIN_FILE="${SCRIPT_DIR}/cmake/arm-none-eabi.cmake" \
    -DTFM_INSTALL_PATH="${TFM_BUILD}/install" \
    -DSTM32CUBE_H5_PATH="${DEPS_DIR}/STM32CubeH5"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Build NS application:"
echo "  cd build_ns && make"
echo ""
echo "Flash (requires STM32CubeProgrammer):"
echo "  ./flash.sh"
echo ""
echo "Hardware connections:"
echo "  UART1 debug: PA9(TX)/PA10(RX) @ 115200 8N1 (managed by TF-M)"
echo "  USB CDC:     micro-USB to CN1"
