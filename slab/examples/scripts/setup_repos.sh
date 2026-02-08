#!/bin/bash
#
# MCUemu Example Repository Setup
#
# Initializes git submodules for SDK dependencies used by firmware examples.
# Core SDKs (STM32CubeF4, CMSIS_5, FreeRTOS-Kernel) are tracked as git
# submodules under slab/examples/repos/.
#
# Copyright (C) 2025 Twisted Wires Security Lab
# SPDX-License-Identifier: GPL-2.0-or-later

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
REPOS_DIR="$SCRIPT_DIR/../repos"

echo "========================================"
echo "MCUemu Example Repository Setup"
echo "========================================"

# =============================================================================
# Core SDKs (git submodules)
# =============================================================================
echo ""
echo "--- Initializing SDK submodules ---"
cd "$REPO_ROOT"

git submodule update --init --depth 1 -- \
    slab/examples/repos/STM32CubeF4 \
    slab/examples/repos/CMSIS_5 \
    slab/examples/repos/FreeRTOS-Kernel

# STM32CubeF4 has nested submodules for HAL driver and CMSIS device headers
echo ""
echo "--- Initializing STM32CubeF4 nested submodules ---"
cd slab/examples/repos/STM32CubeF4
git submodule update --init --depth 1 -- \
    Drivers/STM32F4xx_HAL_Driver \
    Drivers/CMSIS/Device/ST/STM32F4xx
cd "$REPO_ROOT"

# =============================================================================
# Optional: NuttX RTOS (not a submodule, clone on demand)
# =============================================================================
echo ""
echo "--- Apache NuttX (optional) ---"
if [ ! -d "$REPOS_DIR/nuttx" ]; then
    echo "Cloning NuttX..."
    git clone --depth 1 https://github.com/apache/nuttx.git "$REPOS_DIR/nuttx"
else
    echo "NuttX already exists"
fi

if [ ! -d "$REPOS_DIR/nuttx-apps" ]; then
    echo "Cloning NuttX Apps..."
    git clone --depth 1 https://github.com/apache/nuttx-apps.git "$REPOS_DIR/nuttx-apps"
else
    echo "NuttX Apps already exists"
fi

# =============================================================================
# Optional: Zephyr RTOS (not a submodule, clone on demand)
# =============================================================================
echo ""
echo "--- Zephyr RTOS (optional) ---"
if [ ! -d "$REPOS_DIR/zephyr" ]; then
    echo "Cloning Zephyr..."
    git clone --depth 1 https://github.com/zephyrproject-rtos/zephyr.git "$REPOS_DIR/zephyr"
else
    echo "Zephyr already exists"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "========================================"
echo "Repository Setup Complete!"
echo "========================================"
echo ""
echo "SDK repositories:"
ls -1 "$REPOS_DIR"
echo ""
echo "Total size:"
du -sh "$REPOS_DIR"
