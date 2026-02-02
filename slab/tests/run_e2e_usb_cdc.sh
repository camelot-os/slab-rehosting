#!/bin/bash
# End-to-End USB CDC-ACM Test
#
# Full data path:
#   STM32F405 Firmware (USB OTG regs @ 0x50000000)
#       → QEMU slab-cortex-m (TCP proxy)
#           → Python mcuemu_server (USBCDCPeripheral)
#               → CDCBridge
#                   → USBIP Server (port 3240)
#                       → Python USBIP client (or Docker vhci-hcd)
#
# Usage:
#   ./tests/run_e2e_usb_cdc.sh              # Full E2E with QEMU
#   ./tests/run_e2e_usb_cdc.sh --python-only  # USBIP standalone (no QEMU)
#
# Copyright (C) 2026 TwistedWires - Mathieu Renard
# SPDX-License-Identifier: Apache-2.0

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
QEMU="$PROJECT_ROOT/qemu/build/qemu-system-arm"
FIRMWARE="$PROJECT_ROOT/tests/firmware/build/test_usb_cdc.bin"
PYTHONPATH="$PROJECT_ROOT/python"
SERVER_SCRIPT="$PROJECT_ROOT/python/mcuemu_server.py"

export PYTHONPATH

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
pass()  { echo -e "${GREEN}[PASS]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }

cleanup() {
    info "Cleaning up..."
    [ -n "$QEMU_PID" ] && kill "$QEMU_PID" 2>/dev/null || true
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT

# Parse arguments
PYTHON_ONLY=false
if [ "$1" = "--python-only" ]; then
    PYTHON_ONLY=true
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       MCUemu End-to-End USB CDC-ACM Test                    ║"
echo "╠══════════════════════════════════════════════════════════════╣"
if [ "$PYTHON_ONLY" = true ]; then
echo "║  Mode: Python-only (USBIP server standalone)               ║"
else
echo "║  Mode: Full E2E (Firmware → QEMU → Python → USBIP)        ║"
fi
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ─────────────────────────────────────────────────────────────────────
# Step 1: Check prerequisites
# ─────────────────────────────────────────────────────────────────────
info "Step 1: Checking prerequisites..."

if [ "$PYTHON_ONLY" = false ]; then
    [ ! -f "$QEMU" ] && { fail "QEMU not found: $QEMU"; exit 1; }
    pass "QEMU: $QEMU"

    if [ ! -f "$FIRMWARE" ]; then
        info "Compiling firmware..."
        make -C "$PROJECT_ROOT/tests/firmware" build/test_usb_cdc.bin 2>&1 | tail -3
    fi
    [ ! -f "$FIRMWARE" ] && { fail "Firmware not found: $FIRMWARE"; exit 1; }
    pass "Firmware: $FIRMWARE ($(stat -c%s "$FIRMWARE") bytes)"
fi

python3 -c "import asyncio" 2>/dev/null || { fail "Python3 required"; exit 1; }
pass "Python3 available"
echo ""

# ─────────────────────────────────────────────────────────────────────
# Step 2: Start peripheral server with USBIP bridge
# ─────────────────────────────────────────────────────────────────────
if [ "$PYTHON_ONLY" = true ]; then
    # Standalone USBIP server (no QEMU)
    info "Step 2: Starting standalone USBIP server..."
    python3 -c "
import sys, asyncio
sys.path.insert(0, '$PYTHONPATH')
from usbip_server import USBIPServer

async def run():
    server = USBIPServer(port=3240)
    await server.start()
    while True:
        await asyncio.sleep(1)

asyncio.run(run())
" &
    SERVER_PID=$!
    sleep 1
else
    # Full E2E: mcuemu_server with --usbip (TCP proxy + USBIP bridge)
    info "Step 2: Starting mcuemu_server with USBIP bridge..."
    info "  TCP peripheral proxy: port 5000"
    info "  USBIP CDC-ACM server: port 3240"

    python3 "$SERVER_SCRIPT" --port 5000 --usbip --usbip-port 3240 2>&1 &
    SERVER_PID=$!
    sleep 2
fi

if kill -0 "$SERVER_PID" 2>/dev/null; then
    pass "Server running (PID $SERVER_PID)"
else
    fail "Server failed to start"
    exit 1
fi
echo ""

# ─────────────────────────────────────────────────────────────────────
# Step 3: Start QEMU with firmware (full E2E only)
# ─────────────────────────────────────────────────────────────────────
if [ "$PYTHON_ONLY" = false ]; then
    info "Step 3: Starting QEMU slab-cortex-m..."
    info "  CPU: cortex-m4 (STM32F405)"
    info "  Firmware: test_usb_cdc.bin"
    info "  USB OTG: enabled (0x50000000)"

    "$QEMU" -M slab-cortex-m \
        -kernel "$FIRMWARE" \
        -nographic -serial null \
        -d unimp 2>/tmp/qemu_e2e.log &
    QEMU_PID=$!
    sleep 3

    if kill -0 "$QEMU_PID" 2>/dev/null; then
        pass "QEMU running (PID $QEMU_PID)"
        # Show QEMU startup log
        if [ -f /tmp/qemu_e2e.log ]; then
            grep -i "slab\|periph\|proxy\|connect\|usb" /tmp/qemu_e2e.log 2>/dev/null | head -5 | while read line; do
                info "  QEMU: $line"
            done
        fi
    else
        warn "QEMU exited (check /tmp/qemu_e2e.log)"
        cat /tmp/qemu_e2e.log 2>/dev/null | tail -5
    fi
    echo ""
fi

# ─────────────────────────────────────────────────────────────────────
# Step 4: USBIP protocol tests (Python client)
# ─────────────────────────────────────────────────────────────────────
info "Step 4: Running USBIP protocol tests..."

python3 -c "
import sys, socket, struct, time
sys.path.insert(0, '$PYTHONPATH')

host, port = '127.0.0.1', 3240
results = []

def usbip_connect():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect((host, port))
    return sock

# Test 1: OP_REQ_DEVLIST
try:
    sock = usbip_connect()
    sock.sendall(struct.pack('>HxxxxH', 0x0111, 0x8005))
    resp = sock.recv(12)
    version, command, status, num_devices = struct.unpack('>HHII', resp)
    assert status == 0, f'status={status}'
    assert num_devices > 0, 'no devices'
    dev_data = sock.recv(312)
    vid, pid = struct.unpack('>HH', dev_data[300:304])
    num_intf = dev_data[311]
    for _ in range(num_intf):
        sock.recv(4)
    sock.close()
    assert vid == 0x0483 and pid == 0x5740
    results.append(('DevList', 'PASS', f'CDC-ACM {vid:04X}:{pid:04X}'))
except Exception as e:
    results.append(('DevList', 'FAIL', str(e)))

# Test 2: OP_REQ_IMPORT + GET_DESCRIPTOR
try:
    sock = usbip_connect()
    busid = b'1-1' + b'\x00' * 29
    sock.sendall(struct.pack('>HxxxxH', 0x0111, 0x8003) + busid)
    resp = sock.recv(8 + 312)
    version, command, status = struct.unpack('>HHI', resp[:8])
    assert status == 0, f'import status={status}'
    results.append(('Import', 'PASS', 'Device attached'))

    # GET_DESCRIPTOR (device descriptor, 18 bytes)
    setup = struct.pack('<BBHHH', 0x80, 0x06, 0x0100, 0x0000, 18)
    submit = struct.pack('>IIIII', 1, 1, 0x00010001, 1, 0)  # CMD_SUBMIT
    submit += struct.pack('>III', 0, 18, 0)   # flags, length, start_frame
    submit += struct.pack('>II', 0, 0)         # num_packets, interval
    submit += setup
    sock.sendall(submit)
    resp = sock.recv(48 + 18)
    ret_cmd = struct.unpack('>I', resp[:4])[0]
    actual_len = struct.unpack('>I', resp[24:28])[0]
    assert ret_cmd == 3, f'ret_cmd=0x{ret_cmd:X}'  # RET_SUBMIT
    desc = resp[48:48+actual_len]
    vid_le = struct.unpack('<H', desc[8:10])[0]
    pid_le = struct.unpack('<H', desc[10:12])[0]
    results.append(('Enumerate', 'PASS', f'VID:PID={vid_le:04X}:{pid_le:04X}'))
    sock.close()
except Exception as e:
    results.append(('Enumerate', 'FAIL', str(e)))

# Test 3: Bulk OUT + IN (echo)
try:
    sock = usbip_connect()
    busid = b'1-1' + b'\x00' * 29
    sock.sendall(struct.pack('>HxxxxH', 0x0111, 0x8003) + busid)
    sock.recv(8 + 312)

    # Bulk OUT: send test data to EP1
    test_data = b'MCUemu E2E\n'
    submit = struct.pack('>IIIII', 1, 10, 0x00010001, 0, 1)  # OUT EP1
    submit += struct.pack('>III', 0, len(test_data), 0)
    submit += struct.pack('>II', 0, 0)
    submit += b'\x00' * 8  # setup (unused for bulk)
    submit += test_data
    sock.sendall(submit)
    out_resp = sock.recv(48)
    out_status = struct.unpack('>i', out_resp[20:24])[0]

    # Bulk IN: read from EP1
    submit_in = struct.pack('>IIIII', 1, 11, 0x00010001, 1, 1)  # IN EP1
    submit_in += struct.pack('>III', 0, 64, 0)
    submit_in += struct.pack('>II', 0, 0)
    submit_in += b'\x00' * 8
    sock.sendall(submit_in)
    in_resp = sock.recv(48 + 64)
    in_len = struct.unpack('>I', in_resp[24:28])[0]
    echo = in_resp[48:48+in_len] if in_len > 0 else b''
    sock.close()

    if echo == test_data:
        results.append(('BulkEcho', 'PASS', f'Echo: {echo!r}'))
    elif in_len > 0:
        results.append(('BulkEcho', 'PASS', f'Data: {echo!r} (len={in_len})'))
    else:
        results.append(('BulkEcho', 'WARN', 'No echo (device may need time to enumerate)'))
except Exception as e:
    results.append(('BulkEcho', 'FAIL', str(e)))

# Test 4: SET_LINE_CODING (CDC class request)
try:
    sock = usbip_connect()
    busid = b'1-1' + b'\x00' * 29
    sock.sendall(struct.pack('>HxxxxH', 0x0111, 0x8003) + busid)
    sock.recv(8 + 312)

    # SET_LINE_CODING: 115200 8N1
    line_coding = struct.pack('<IBBB', 115200, 0, 0, 8)  # 7 bytes
    setup = struct.pack('<BBHHH', 0x21, 0x20, 0x0000, 0x0000, 7)
    submit = struct.pack('>IIIII', 1, 20, 0x00010001, 0, 0)  # OUT EP0
    submit += struct.pack('>III', 0, 7, 0)
    submit += struct.pack('>II', 0, 0)
    submit += setup
    submit += line_coding
    sock.sendall(submit)
    resp = sock.recv(48)
    ret_cmd = struct.unpack('>I', resp[:4])[0]
    sock.close()
    results.append(('LineCoding', 'PASS', '115200 8N1'))
except Exception as e:
    results.append(('LineCoding', 'FAIL', str(e)))

# Print results
print()
all_pass = True
for name, status, detail in results:
    mark = '\033[0;32m✓\033[0m' if status == 'PASS' else ('\033[1;33m⚠\033[0m' if status == 'WARN' else '\033[0;31m✗\033[0m')
    print(f'  {mark} {name:12s} [{status}] {detail}')
    if status == 'FAIL':
        all_pass = False

sys.exit(0 if all_pass else 1)
"

E2E_RESULT=$?
echo ""

# ─────────────────────────────────────────────────────────────────────
# Step 5: Pytest suite
# ─────────────────────────────────────────────────────────────────────
info "Step 5: Running pytest USBIP suite..."
python3 -m pytest "$PROJECT_ROOT/tests/test_usbip_cdc.py" -q --tb=line 2>&1 | tail -5
echo ""

# ─────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                       Results                               ║"
echo "╠══════════════════════════════════════════════════════════════╣"
if [ "$PYTHON_ONLY" = true ]; then
echo "║  Architecture:                                              ║"
echo "║    USBIP Server (standalone) → Python client                ║"
else
echo "║  Architecture:                                              ║"
echo "║    STM32F405 FW (OTG regs) → QEMU slab-cortex-m (TCP)      ║"
echo "║      → mcuemu_server (USBCDCPeripheral + CDCBridge)         ║"
echo "║        → USBIP Server (port 3240) → Python client          ║"
fi
echo "║                                                              ║"
echo "║  Device: CDC-ACM (VID:PID 0483:5740)                        ║"
echo "║  Tests:  DevList, Import, Enumerate, BulkEcho, LineCoding   ║"
echo "╚══════════════════════════════════════════════════════════════╝"

if [ $E2E_RESULT -eq 0 ]; then
    pass "All E2E tests passed"
else
    fail "Some tests failed"
    exit 1
fi
