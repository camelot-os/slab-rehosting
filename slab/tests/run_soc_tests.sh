#!/bin/bash
#
# MCUemu SoC-Specific Test Runner
#
# Runs tests for different SoC targets using the appropriate
# configuration files and peripheral emulation.
#
# Copyright (C) 2025 Twisted Wires Security Lab
# SPDX-License-Identifier: GPL-2.0-or-later
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
QEMU_BIN="$PROJECT_DIR/qemu/build/qemu-system-arm"
FIRMWARE_DIR="$SCRIPT_DIR/firmware"
PYTHON_DIR="$PROJECT_DIR/python"
CONFIG_DIR="$PROJECT_DIR/configs"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

TIMEOUT=30
VERBOSE=0
TEST_PORT=5000

usage() {
    echo "Usage: $0 [-v] [-t timeout] [soc_name...]"
    echo ""
    echo "Options:"
    echo "  -v          Verbose output"
    echo "  -t timeout  Test timeout in seconds (default: $TIMEOUT)"
    echo ""
    echo "Available SoCs:"
    echo "  stm32f4     STM32F405 (Cortex-M4 @ 168MHz)"
    echo "  nrf52840    nRF52840 (Cortex-M4 @ 64MHz)"
    echo "  lpc55s69    LPC55S69 (Cortex-M33 + TrustZone)"
    echo "  stm32h7     STM32H7 (Cortex-M7 + M4 dual-core)"
    echo "  all         Run all available tests"
    echo ""
    echo "Examples:"
    echo "  $0                    # Run all tests"
    echo "  $0 stm32f4            # Test STM32F4 only"
    echo "  $0 -v stm32f4 nrf52840  # Verbose tests"
}

while getopts "vt:h" opt; do
    case $opt in
        v) VERBOSE=1 ;;
        t) TIMEOUT=$OPTARG ;;
        h) usage; exit 0 ;;
        ?) usage; exit 1 ;;
    esac
done
shift $((OPTIND-1))

# Default to all tests
if [ $# -eq 0 ] || [ "$1" = "all" ]; then
    SOCS="stm32f4 nrf52840"
else
    SOCS="$@"
fi

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║              MCUemu SoC-Specific Test Suite                  ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check prerequisites
check_prereqs() {
    echo -e "${YELLOW}Checking prerequisites...${NC}"

    if ! command -v arm-none-eabi-gcc &> /dev/null; then
        echo -e "${RED}ERROR: arm-none-eabi-gcc not found${NC}"
        exit 1
    fi
    echo "  ✓ ARM toolchain"

    if [ ! -x "$QEMU_BIN" ]; then
        echo -e "${RED}ERROR: QEMU binary not found${NC}"
        exit 1
    fi
    echo "  ✓ QEMU binary"

    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}ERROR: python3 not found${NC}"
        exit 1
    fi
    echo "  ✓ Python3"

    if [ ! -f "$PYTHON_DIR/mcuemu_server.py" ]; then
        echo -e "${RED}ERROR: mcuemu_server.py not found${NC}"
        exit 1
    fi
    echo "  ✓ MCUemu server"

    echo ""
}

# Build SoC-specific firmware
build_firmware() {
    echo -e "${YELLOW}Building SoC-specific firmware...${NC}"

    cd "$FIRMWARE_DIR/soc"

    # Build all SoC tests
    if make 2>&1 | grep -E "^(arm-none|Error|error:)" | head -10; then
        if [ -f "../build/soc/stm32f4_test.bin" ]; then
            echo -e "  ${GREEN}✓ SoC firmware built${NC}"
        else
            echo -e "  ${RED}✗ Build may have failed${NC}"
        fi
    fi

    cd "$SCRIPT_DIR"
    echo ""
}

# Get SoC configuration
get_soc_config() {
    local soc=$1
    case $soc in
        stm32f4)
            echo "stm32f405.yaml"
            ;;
        nrf52840)
            echo "nrf52840.yaml"
            ;;
        lpc55s69)
            echo "lpc55s69.yaml"
            ;;
        stm32h7)
            echo "stm32h7_dual.yaml"
            ;;
        *)
            echo ""
            ;;
    esac
}

# Get CPU type for SoC
get_cpu_type() {
    local soc=$1
    case $soc in
        stm32f4)
            echo "cortex-m4"
            ;;
        nrf52840)
            echo "cortex-m4"
            ;;
        lpc55s69)
            echo "cortex-m33"
            ;;
        stm32h7)
            echo "cortex-m7"
            ;;
        *)
            echo "cortex-m4"
            ;;
    esac
}

# Run single SoC test
run_soc_test() {
    local soc=$1
    local firmware="$FIRMWARE_DIR/build/soc/${soc}_test.bin"
    local config=$(get_soc_config $soc)
    local cpu=$(get_cpu_type $soc)
    local output_file=$(mktemp)

    if [ ! -f "$firmware" ]; then
        echo -e "  ${YELLOW}⊘ $soc${NC} (firmware not built)"
        return 2
    fi

    echo -ne "  ${CYAN}$soc${NC} ($cpu): "

    # Start peripheral server with config (always verbose to capture result)
    local server_args="-p $TEST_PORT -v"
    if [ -n "$config" ] && [ -f "$CONFIG_DIR/$config" ]; then
        server_args="$server_args --config $CONFIG_DIR/$config"
    fi

    python3 "$PYTHON_DIR/mcuemu_server.py" $server_args >"$output_file" 2>&1 &
    local server_pid=$!
    sleep 1

    # Run QEMU with short timeout (tests should complete quickly)
    local qemu_args="-M mcuemu -cpu $cpu -kernel $firmware -nographic"
    timeout $TIMEOUT "$QEMU_BIN" $qemu_args >/dev/null 2>&1 &
    local qemu_pid=$!

    # Wait for QEMU to finish or timeout
    wait $qemu_pid 2>/dev/null || true

    # Kill the server
    kill $server_pid 2>/dev/null || true
    wait $server_pid 2>/dev/null || true

    # Parse server output to determine result
    # Look for final test result write to 0x4000F000
    # Format: "Unmapped write[S]: 0x4000F000 <- 0x0000000X"
    # Value 1 = PASS, Value 2 = FAIL
    local last_result=$(grep "0x4000F000 <-" "$output_file" | tail -1 | grep -oP '0x[0-9A-Fa-f]+$' || echo "0")

    if [ $VERBOSE -eq 1 ]; then
        cat "$output_file"
    fi
    rm -f "$output_file"

    # Check result: 0x00000001 = PASS, 0x00000002 = FAIL
    if [ "$last_result" = "0x00000001" ]; then
        echo -e "${GREEN}PASS${NC}"
        return 0
    elif [ "$last_result" = "0x00000002" ]; then
        echo -e "${RED}FAIL${NC}"
        return 1
    else
        echo -e "${YELLOW}INCOMPLETE${NC}"
        return 1
    fi
}

# Main
check_prereqs
build_firmware

passed=0
failed=0
skipped=0

echo -e "${YELLOW}Running SoC tests...${NC}"
echo ""

for soc in $SOCS; do
    result=0
    run_soc_test "$soc" || result=$?

    case $result in
        0) passed=$((passed + 1)) ;;
        1) failed=$((failed + 1)) ;;
        2) skipped=$((skipped + 1)) ;;
    esac

    # Wait for port to be released and kill any remaining processes
    sleep 2
    fuser -k $TEST_PORT/tcp 2>/dev/null || true
done

echo ""
echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
echo -e "  ${GREEN}Passed:${NC}  $passed"
echo -e "  ${RED}Failed:${NC}  $failed"
echo -e "  ${YELLOW}Skipped:${NC} $skipped"
echo ""

if [ $failed -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed.${NC}"
    exit 1
fi
