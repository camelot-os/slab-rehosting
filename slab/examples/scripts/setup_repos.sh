#!/bin/bash
#
# MCUemu Example Repository Setup
#
# This script clones and sets up all required repositories for the examples.
#
# Copyright (C) 2025 TwistedWires Security Lab
# SPDX-License-Identifier: GPL-2.0-or-later

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLES_DIR="$(dirname "$SCRIPT_DIR")"
REPOS_DIR="$EXAMPLES_DIR/repos"

echo "========================================"
echo "MCUemu Example Repository Setup"
echo "========================================"

mkdir -p "$REPOS_DIR"
cd "$REPOS_DIR"

# =============================================================================
# STM32CubeF4 (HAL/LL Drivers)
# =============================================================================
echo ""
echo "--- STM32CubeF4 (HAL Drivers) ---"
if [ ! -d "STM32CubeF4" ]; then
    echo "Cloning STM32CubeF4..."
    git clone --depth 1 https://github.com/STMicroelectronics/STM32CubeF4.git
else
    echo "STM32CubeF4 already exists, updating..."
    cd STM32CubeF4 && git pull && cd ..
fi

# =============================================================================
# CMSIS (ARM headers)
# =============================================================================
echo ""
echo "--- CMSIS ---"
if [ ! -d "CMSIS_5" ]; then
    echo "Cloning CMSIS_5..."
    git clone --depth 1 https://github.com/ARM-software/CMSIS_5.git
else
    echo "CMSIS_5 already exists"
fi

# =============================================================================
# FreeRTOS Kernel
# =============================================================================
echo ""
echo "--- FreeRTOS Kernel ---"
if [ ! -d "FreeRTOS-Kernel" ]; then
    echo "Cloning FreeRTOS-Kernel..."
    git clone --depth 1 https://github.com/FreeRTOS/FreeRTOS-Kernel.git
else
    echo "FreeRTOS-Kernel already exists, updating..."
    cd FreeRTOS-Kernel && git pull && cd ..
fi

# =============================================================================
# NuttX RTOS
# =============================================================================
echo ""
echo "--- Apache NuttX ---"
if [ ! -d "nuttx" ]; then
    echo "Cloning NuttX..."
    git clone --depth 1 https://github.com/apache/nuttx.git
else
    echo "NuttX already exists, updating..."
    cd nuttx && git pull && cd ..
fi

if [ ! -d "nuttx-apps" ]; then
    echo "Cloning NuttX Apps..."
    git clone --depth 1 https://github.com/apache/nuttx-apps.git apps
else
    echo "NuttX Apps already exists"
fi

# =============================================================================
# Zephyr RTOS
# =============================================================================
echo ""
echo "--- Zephyr RTOS ---"
if [ ! -d "zephyr" ]; then
    echo "Cloning Zephyr..."
    git clone --depth 1 https://github.com/zephyrproject-rtos/zephyr.git
else
    echo "Zephyr already exists, updating..."
    cd zephyr && git pull && cd ..
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "========================================"
echo "Repository Setup Complete!"
echo "========================================"
echo ""
echo "Cloned repositories:"
ls -1 "$REPOS_DIR"
echo ""
echo "Total size:"
du -sh "$REPOS_DIR"
