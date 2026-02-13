#!/bin/bash
#
# MCUemu Test Runner
#
# This script builds and runs all MCUemu tests.
#
# Copyright (C) 2025 Twisted Wires Security Lab
# SPDX-License-Identifier: GPL-2.0-or-later
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
QEMU_DIR="$PROJECT_DIR/qemu"
QEMU_BIN="$QEMU_DIR/build/qemu-system-arm"
FIRMWARE_DIR="$SCRIPT_DIR/firmware"
SCRIPTS_DIR="$SCRIPT_DIR/scripts"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test configuration
TIMEOUT=30
VERBOSE=0
TEST_PORT=5000

# Parse arguments
while getopts "vt:p:h" opt; do
    case $opt in
        v) VERBOSE=1 ;;
        t) TIMEOUT=$OPTARG ;;
        p) TEST_PORT=$OPTARG ;;
        h)
            echo "Usage: $0 [-v] [-t timeout] [-p port] [test_name...]"
            echo ""
            echo "Options:"
            echo "  -v          Verbose output"
            echo "  -t timeout  Test timeout in seconds (default: $TIMEOUT)"
            echo "  -p port     TCP port for peripheral server (default: $TEST_PORT)"
            echo ""
            echo "Available tests:"
            echo "  basic       - Basic operation test"
            echo "  gpio        - GPIO via TCP proxy"
            echo "  uart        - UART via TCP proxy"
            echo "  systick     - SysTick timer"
            echo "  nvic        - NVIC interrupts"
            echo "  dualcore    - Dual-core IPC"
            echo "  trustzone   - TrustZone (ARMv8-M)"
            echo "  all         - Run all tests (default)"
            exit 0
            ;;
        ?) exit 1 ;;
    esac
done
shift $((OPTIND-1))

# Tests to run
if [ $# -eq 0 ]; then
    TESTS="basic gpio uart systick nvic"
else
    TESTS="$@"
fi

# Expand "all" to all tests
if [ "$TESTS" = "all" ]; then
    TESTS="basic gpio uart systick nvic dualcore trustzone"
fi

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                   MCUemu Test Suite                          ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check prerequisites
check_prereqs() {
    echo -e "${YELLOW}Checking prerequisites...${NC}"

    # Check for ARM toolchain
    if ! command -v arm-none-eabi-gcc &> /dev/null; then
        echo -e "${RED}ERROR: arm-none-eabi-gcc not found${NC}"
        echo "Install with: sudo apt install gcc-arm-none-eabi"
        exit 1
    fi
    echo "  ✓ ARM toolchain found"

    # Check for QEMU binary
    if [ ! -x "$QEMU_BIN" ]; then
        echo -e "${RED}ERROR: QEMU binary not found at $QEMU_BIN${NC}"
        echo "Build QEMU first with: ./build_mcuemu.sh qemu"
        exit 1
    fi
    echo "  ✓ QEMU binary found"

    # Check for Python
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}ERROR: python3 not found${NC}"
        exit 1
    fi
    echo "  ✓ Python3 found"

    echo ""
}

# Build firmware
build_firmware() {
    echo -e "${YELLOW}Building test firmware...${NC}"
    cd "$FIRMWARE_DIR"
    make clean 2>/dev/null || true
    if make; then
        echo -e "  ${GREEN}✓ Firmware built successfully${NC}"
    else
        echo -e "  ${RED}✗ Firmware build failed${NC}"
        exit 1
    fi
    echo ""
    cd "$SCRIPT_DIR"
}

# Run a single test
run_test() {
    local test_name=$1
    local firmware="$FIRMWARE_DIR/build/test_${test_name}.bin"
    local cpu_type="cortex-m4"
    local extra_props=""

    # Special cases
    case $test_name in
        trustzone)
            cpu_type="cortex-m33"
            ;;
        dualcore)
            extra_props=",dual-core=true"
            ;;
    esac

    if [ ! -f "$firmware" ]; then
        echo -e "  ${RED}✗ Firmware not found: $firmware${NC}"
        return 1
    fi

    echo -e "  Running ${BLUE}$test_name${NC} (CPU: $cpu_type)..."

    # Start test server in background
    local server_args=""
    [ $VERBOSE -eq 1 ] && server_args="-v"

    python3 "$SCRIPTS_DIR/test_server.py" -p $TEST_PORT -t $TIMEOUT $server_args &
    local server_pid=$!

    # Give server time to start
    sleep 0.5

    # Run QEMU with test firmware
    local qemu_args="-M slab-cortex-m,cpu-type=$cpu_type,tcp-port=${TEST_PORT}${extra_props} -kernel $firmware"
    qemu_args="$qemu_args -nographic -serial null"

    if [ $VERBOSE -eq 1 ]; then
        echo "    QEMU: $QEMU_BIN $qemu_args"
    fi

    # Run QEMU with timeout
    timeout $TIMEOUT "$QEMU_BIN" $qemu_args 2>&1 | while IFS= read -r line; do
        if [ $VERBOSE -eq 1 ]; then
            echo "    QEMU: $line"
        fi
    done &
    local qemu_pid=$!

    # Wait for server to finish (it exits on test completion)
    wait $server_pid 2>/dev/null
    local result=$?

    # Kill QEMU if still running
    kill $qemu_pid 2>/dev/null || true
    wait $qemu_pid 2>/dev/null || true

    return $result
}

# Main execution
check_prereqs
build_firmware

# Results tracking
PASSED=0
FAILED=0
SKIPPED=0

echo -e "${YELLOW}Running tests...${NC}"
echo ""

for test in $TESTS; do
    # Check if it's a special test that might be skipped
    case $test in
        trustzone)
            # Check if we have M33 support
            if ! arm-none-eabi-gcc -mcpu=cortex-m33 -x c -c /dev/null -o /dev/null 2>/dev/null; then
                echo -e "  ${YELLOW}⊘ $test${NC} (skipped - no M33 toolchain support)"
                ((SKIPPED++))
                continue
            fi
            ;;
    esac

    if run_test "$test"; then
        echo -e "  ${GREEN}✓ $test${NC} PASSED"
        ((PASSED++))
    else
        echo -e "  ${RED}✗ $test${NC} FAILED"
        ((FAILED++))
    fi

    # Wait between tests
    sleep 0.5
done

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                      Test Summary                            ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}Passed:${NC}  $PASSED"
echo -e "  ${RED}Failed:${NC}  $FAILED"
echo -e "  ${YELLOW}Skipped:${NC} $SKIPPED"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed.${NC}"
    exit 1
fi
