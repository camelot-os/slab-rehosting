#!/bin/bash
#
# MCUemu Complete Test Suite
#
# Runs all MCUemu tests:
# 1. Python unit tests
# 2. Firmware validation tests
# 3. SoC-specific tests
#
# Copyright (C) 2025 Twisted Wires Security Lab
# SPDX-License-Identifier: GPL-2.0-or-later

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCUEMU_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
TESTS_DIR="$MCUEMU_DIR/tests"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "MCUemu Complete Test Suite"
echo "========================================"
echo "Date: $(date)"
echo "Directory: $MCUEMU_DIR"
echo ""

# Track results
PASSED=0
FAILED=0
SKIPPED=0

run_test() {
    local name="$1"
    local cmd="$2"

    echo -n "[$name] "

    if output=$(eval "$cmd" 2>&1); then
        if echo "$output" | grep -q "PASSED\|passed"; then
            echo -e "${GREEN}PASS${NC}"
            ((PASSED++))
            return 0
        fi
    fi

    if echo "$output" | grep -q "SKIP\|skipped"; then
        echo -e "${YELLOW}SKIP${NC}"
        ((SKIPPED++))
        return 0
    fi

    echo -e "${RED}FAIL${NC}"
    echo "$output" | tail -5
    ((FAILED++))
    return 1
}

# =============================================================================
# Python Unit Tests
# =============================================================================
echo ""
echo "--- Python Unit Tests ---"
cd "$TESTS_DIR"

run_test "HIL Tests" "python3 test_hil.py"
run_test "USBIP CDC Tests" "python3 test_usbip_cdc.py"
run_test "SVD Parser Tests" "python3 test_svd_parser.py"
run_test "Dual-MCU SPI Tests" "python3 test_dual_mcu_spi.py"
run_test "TrustZone Tests" "python3 test_trustzone.py"
run_test "Bootrom Tests" "python3 test_bootrom.py"

# =============================================================================
# Firmware Tests
# =============================================================================
echo ""
echo "--- Firmware Tests ---"
cd "$TESTS_DIR/firmware"

# Check if firmware is built
if [ -f "build/test_basic.bin" ]; then
    run_test "Basic Firmware" "python3 $SCRIPT_DIR/test_firmware.py build/test_basic.bin"
else
    echo -e "Basic Firmware: ${YELLOW}SKIP${NC} (not built)"
    ((SKIPPED++))
fi

# =============================================================================
# SoC Tests
# =============================================================================
echo ""
echo "--- SoC Tests ---"
cd "$TESTS_DIR/firmware/soc"

if [ -f "stm32f4/build/stm32f4_test.bin" ]; then
    run_test "STM32F4 SoC" "python3 $SCRIPT_DIR/test_firmware.py stm32f4/build/stm32f4_test.bin"
else
    echo -e "STM32F4 SoC: ${YELLOW}SKIP${NC} (not built)"
    ((SKIPPED++))
fi

if [ -f "nrf52840/build/nrf52840_test.bin" ]; then
    run_test "nRF52840 SoC" "python3 $SCRIPT_DIR/test_firmware.py nrf52840/build/nrf52840_test.bin"
else
    echo -e "nRF52840 SoC: ${YELLOW}SKIP${NC} (not built)"
    ((SKIPPED++))
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "========================================"
echo "Test Summary"
echo "========================================"
echo -e "Passed:  ${GREEN}$PASSED${NC}"
echo -e "Failed:  ${RED}$FAILED${NC}"
echo -e "Skipped: ${YELLOW}$SKIPPED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
