# MCUemu Peripheral Proxy Benchmark Guide

This document explains the TCP vs SHM peripheral proxy performance benchmarks and provides a step-by-step tutorial for running your own measurements.

## Table of Contents

1. [Overview](#overview)
2. [Proxy Modes Explained](#proxy-modes-explained)
3. [Benchmark Results](#benchmark-results)
4. [Understanding the Metrics](#understanding-the-metrics)
5. [Step-by-Step Tutorial](#step-by-step-tutorial)
6. [Firmware Requirements](#firmware-requirements)
7. [Troubleshooting](#troubleshooting)

---

## Overview

MCUemu uses a peripheral proxy architecture where QEMU forwards Memory-Mapped I/O (MMIO) accesses to a Python server for emulation. This allows flexible, scriptable peripheral models without modifying QEMU.

```
┌─────────────────┐     MMIO      ┌─────────────────┐
│   QEMU          │ ───────────── │  Python Server  │
│   (Cortex-M)    │   TCP/SHM     │  (Peripherals)  │
└─────────────────┘               └─────────────────┘
```

Two proxy transport modes are available:

| Mode | Transport | Use Case |
|------|-----------|----------|
| **TCP** | TCP socket (localhost:5560) | Remote debugging, Docker, network isolation |
| **SHM** | Shared memory (`/dev/shm`) | High-performance local emulation |

---

## Proxy Modes Explained

### TCP Proxy

TCP proxy uses standard socket communication:

```
QEMU                          Python Server
  │                                │
  │──── 'R' + addr + size ────────▶│  (10 bytes)
  │                                │
  │◀─── result + status ───────────│  (5 bytes)
  │                                │
```

**Advantages:**
- Works across network/containers
- Easy to debug with packet capture
- No shared memory setup required

**Disadvantages:**
- Higher latency (~3-10 µs per operation)
- Limited by TCP stack overhead

### SHM Proxy

SHM proxy uses a memory-mapped region:

```
Shared Memory Layout (v1 protocol):
┌────────┬─────────┬─────────┬────────┬─────────┬──────┬──────┬─────┐
│ Magic  │ Version │ Command │ Status │ Address │ Data │ Size │ Seq │
│ 4 bytes│ 4 bytes │ 4 bytes │ 4 bytes│ 4 bytes │4 bytes│4 bytes│4 bytes│
└────────┴─────────┴─────────┴────────┴─────────┴──────┴──────┴─────┘
  0x534C4142  1       1-6       0/1
              ("SLAB")         (done)
```

**Command codes:**
- 1: READ8, 2: READ16, 3: READ32
- 4: WRITE8, 5: WRITE16, 6: WRITE32

**Advantages:**
- Lower latency (~2-4 µs per operation)
- Higher throughput (10x faster)
- No network stack overhead

**Disadvantages:**
- Local only (same machine)
- Requires `/dev/shm` access

---

## Benchmark Results

### Test Environment

- **CPU:** Intel/AMD x86_64
- **OS:** Linux 6.1
- **QEMU:** slab-cortex-m machine (Cortex-M4)
- **Python:** 3.11

### Throughput Comparison

| Firmware | TCP (ops/s) | SHM (ops/s) | Speedup |
|----------|-------------|-------------|---------|
| CubeMX Blinky | 1,029 | 979 | 0.95x |
| FreeRTOS | 1,050 | 1,020 | 0.97x |
| Zephyr RTOS | 12,700 | 133,000 | **10.5x** |
| NuttX | 13,100 | 135,000 | **10.3x** |

**Key insight:** SHM advantage only shows with high-frequency peripheral access. Simple firmwares (CubeMX, FreeRTOS) complete in ~100 operations, too few to measure the difference.

### Latency Comparison (Zephyr, 90K+ operations)

| Metric | TCP | SHM | Improvement |
|--------|-----|-----|-------------|
| **Average** | 2.79 µs | 2.31 µs | 17% faster |
| **Median** | 3.42 µs | 2.93 µs | 14% faster |
| **P99** | 7.05 µs | 3.84 µs | **46% faster** |
| **Min** | 1.82 µs | 1.33 µs | 27% faster |

**P99 (99th percentile):** 99% of operations complete faster than this value. Lower P99 means more consistent performance.

### Boot Timing

Time from QEMU start to firmware milestones:

| Milestone | Time (ms) | Description |
|-----------|-----------|-------------|
| First MMIO Access | 231-234 | QEMU initialization complete |
| UART Ready | 260 | Clock + GPIO + UART configured |
| UART First TX | 262 | Firmware sends first byte |

Boot time is dominated by QEMU startup (~230ms), not the proxy.

---

## Understanding the Metrics

### Throughput (ops/sec)

Number of MMIO operations processed per second:
```
Throughput = Total Operations / Test Duration
```

Higher is better. SHM achieves 10x higher throughput for UART-heavy workloads.

### Latency

Time to complete a single MMIO operation (microseconds):

- **Average:** Mean latency across all operations
- **Median (P50):** Middle value, less affected by outliers
- **P99:** 99% of operations are faster than this
- **Min/Max:** Best and worst case

### Why P99 Matters

For real-time firmware, worst-case latency matters more than average:

```
Example: 100,000 operations
- Average: 3 µs (acceptable)
- P99: 50 µs (1000 operations slower than 50 µs!)
```

High P99 can cause timing-sensitive firmware to miss deadlines.

---

## Step-by-Step Tutorial

### Prerequisites

```bash
# 1. Build QEMU with slab-cortex-m machine
cd qemu && mkdir build && cd build
../configure --target-list=arm-softmmu
make -j$(nproc)

# 2. Build test firmware
cd examples/cortex-m/stm32/f405/rtos/cubemx_blinky && make
cd examples/cortex-m/stm32/f405/demos/hello_blink_uart && make

# 3. Install Python dependencies
pip install pytest
```

### Running the Benchmark

#### Basic Usage

```bash
# Default benchmark (HelloBlinkUart, both TCP and SHM)
python3 examples/scripts/benchmark_proxy.py

# Specific firmware
python3 examples/scripts/benchmark_proxy.py --firmware zephyr

# Quiet mode (cleaner measurements)
python3 examples/scripts/benchmark_proxy.py --firmware zephyr --quiet

# Longer timeout for slower firmwares
python3 examples/scripts/benchmark_proxy.py --timeout 10
```

#### Available Firmwares

| Name | Binary | Operations | Notes |
|------|--------|------------|-------|
| `cubemx` | cortex-m/stm32/f405/rtos/cubemx_blinky/build/blinky.bin | ~100 | Simple, fast completion |
| `freertos` | cortex-m/stm32/f405/rtos/freertos_blinky/build/freertos_blinky.bin | ~100 | Multi-task blink |
| `zephyr` | cortex-m/stm32/f407/rtos/zephyr_blinky/build/zephyr.bin | 90K+ | Best for benchmarking |
| `helloblinkuart` | cortex-m/stm32/f405/demos/hello_blink_uart/build/HelloBlinkUart.bin | 260K+ | Needs interrupts |

#### TCP-Only or SHM-Only

```bash
# Only test TCP proxy
python3 examples/scripts/benchmark_proxy.py --tcp-only

# Only test SHM proxy
python3 examples/scripts/benchmark_proxy.py --shm-only
```

### Manual Testing

#### TCP Proxy

Terminal 1 - Start Python server:
```bash
python3 python/mcuemu_server.py --port 5560
```

Terminal 2 - Start QEMU:
```bash
./qemu/build/qemu-system-arm \
    -M slab-cortex-m,proxy-mode=tcp,tcp-port=5560 \
    -kernel examples/cortex-m/stm32/f407/rtos/zephyr_blinky/build/zephyr.bin \
    -nographic
```

#### SHM Proxy

Terminal 1 - Start Python server:
```bash
python3 python/mcuemu_server.py --shm-name=/slab_peripheral
```

Terminal 2 - Start QEMU:
```bash
./qemu/build/qemu-system-arm \
    -M slab-cortex-m,proxy-mode=shm,shm-name=/slab_peripheral \
    -kernel examples/cortex-m/stm32/f407/rtos/zephyr_blinky/build/zephyr.bin \
    -nographic
```

### Interpreting Results

```
================================================================================
  TCP vs SHM Proxy Performance Comparison
================================================================================

  Metric                                          TCP                  SHM    Speedup
  ------------------------------------------------------------------------------
  Status                                      timeout              timeout
  Total Operations                              38113               405136
  Throughput (ops/sec)                          12689               131218     10.34x
                                                  ▲                    ▲         ▲
                                                  │                    │         │
                                          TCP result          SHM result    SHM/TCP
```

- **Status:** `pass` = test completed, `timeout` = still running (OK for high-op firmwares)
- **Total Operations:** More operations = more accurate latency measurements
- **Speedup:** Values >1x mean SHM is faster

---

## Firmware Requirements

### For Accurate Benchmarking

Best firmwares for benchmarking:
1. **High operation count** (>10K) for statistical significance
2. **No interrupt dependencies** for simple proxy servers
3. **Deterministic behavior** for reproducible results

### Test Interface

Firmwares use a memory-mapped test interface at `0x4000F000`:

```c
#define MCUEMU_TEST_BASE    0x4000F000
#define MCUEMU_TEST_STATUS  (*(volatile uint32_t *)(MCUEMU_TEST_BASE + 0x00))
#define MCUEMU_TEST_DATA    (*(volatile uint32_t *)(MCUEMU_TEST_BASE + 0x04))

#define TEST_STATUS_RUNNING 0x01
#define TEST_STATUS_PASS    0x02
#define TEST_STATUS_FAIL    0x03

// Usage:
MCUEMU_TEST_STATUS = TEST_STATUS_PASS;  // Signal completion
```

### Why HelloBlinkUart Shows "fail" with SHM

HelloBlinkUart requires TIM2 interrupts to pass:
```c
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim) {
    led_toggle_count++;  // Incremented by interrupt
}

// Main loop waits for 10 toggles
if (led_toggle_count >= 10) {
    MCUEMU_TEST_STATUS = TEST_STATUS_PASS;
}
```

The benchmark's simple server doesn't deliver interrupts, so the test never completes. This is expected behavior, not a bug.

---

## Troubleshooting

### SHM "fail" or Low Operation Count

**Symptom:** SHM shows <100 operations or "fail" status

**Causes:**
1. **Firmware needs interrupts** - Use simpler firmware
2. **Protocol mismatch** - Verify QEMU uses v1 32-bit protocol
3. **SHM permissions** - Check `/dev/shm` access

**Fix:**
```bash
# Check SHM region
ls -la /dev/shm/slab*

# Clean up stale regions
rm /dev/shm/slab_*
```

### TCP Connection Refused

**Symptom:** QEMU fails to connect

**Fix:**
```bash
# Ensure server is running first
python3 python/mcuemu_server.py --port 5560 &
sleep 1
# Then start QEMU
```

### Inconsistent Results

**Symptom:** Throughput varies significantly between runs

**Causes:**
1. **Low operation count** - Use firmware with >10K operations
2. **System load** - Close other applications
3. **CPU frequency scaling** - Use performance governor

**Fix:**
```bash
# Set CPU to performance mode
sudo cpupower frequency-set -g performance

# Run multiple iterations
for i in {1..5}; do
    python3 examples/scripts/benchmark_proxy.py --firmware zephyr --quiet
done
```

---

## Recommendations

| Scenario | Recommended Proxy |
|----------|-------------------|
| Docker/container environment | TCP |
| Remote debugging | TCP |
| Maximum performance | SHM |
| High-frequency peripheral (UART, SPI) | SHM |
| Simple GPIO toggling | Either (no significant difference) |

**Rule of thumb:** If your firmware does >10K peripheral accesses, use SHM for 10x better performance.

---

## References

- [MCUemu README](../../README.md)
- [RTOS Examples](../README.md)
- [Benchmark Script](../scripts/benchmark_proxy.py)
