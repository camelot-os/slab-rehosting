# Slab HW

Hardware attack interface module for the Slab security analysis framework.

## Features

- **Lascar Integration**: Side-channel trace acquisition (Ledger)
- **LaseStudio Integration**: Laser fault injection control (Ledger)
- **BlackPill Target**: STM32F4-based glitch/SCA test target board
- **ChipWhisperer Support**: NewAE Technology platform compatibility
- **Hardware-in-the-Loop**: Bridge emulated and real hardware testing
- **Avatar2 Compatible**: Drop-in replacement API for Avatar2 users

## Installation

```bash
# Standalone installation (base classes only)
pip install slab-hw

# With Lascar support
pip install slab-hw[lascar]

# With ChipWhisperer support
pip install slab-hw[chipwhisperer]

# Full installation with all backends
pip install slab-hw[full]

# Development installation
pip install -e .[dev]
```

## Quick Start

### 1. Hardware-in-the-Loop (HIL) Testing

```python
from slab_hw import HILBridge, HILConfiguration, GDBTarget

# Configure HIL bridge
config = HILConfiguration(
    target_type="gdb",
    gdb_host="localhost",
    gdb_port=3333,
    firmware_path="firmware.elf"
)

# Create bridge
bridge = HILBridge(config)
bridge.connect()

# Load firmware
bridge.load_firmware()

# Run to breakpoint
bridge.set_breakpoint(0x08001234)
bridge.run()
bridge.wait_for_halt()

# Read registers and memory
pc = bridge.read_register("pc")
stack = bridge.read_memory(0x20000000, 256)
print(f"PC: 0x{pc:08X}")
print(f"Stack: {stack[:16].hex()}")

# Cleanup
bridge.disconnect()
```

### 2. ChipWhisperer Integration

```python
from slab_hw import create_cw_interface

# Connect to ChipWhisperer
cw = create_cw_interface()
cw.connect()

# Configure scope for power analysis
cw.scope.configure(
    samples=5000,
    offset=0,
    presamples=0,
    gain=45
)

# Arm and capture trace
cw.arm()
cw.target.send(plaintext)  # Trigger encryption
trace = cw.capture()

print(f"Captured {len(trace)} samples")

# Export traces for analysis
import numpy as np
traces = []
plaintexts = []

for i in range(1000):
    pt = np.random.bytes(16)
    cw.arm()
    cw.target.send(pt)
    trace = cw.capture()
    traces.append(trace)
    plaintexts.append(pt)

np.save("traces.npy", np.array(traces))
np.save("plaintexts.npy", np.array(plaintexts))
```

### 3. Lascar Side-Channel Analysis

```python
from slab_hw import create_lascar_session, LascarCPA

# Create Lascar session from traces
session = create_lascar_session(
    traces="traces.npy",
    plaintexts="plaintexts.npy"
)

# Run CPA attack on first key byte
cpa = LascarCPA(session, byte_index=0)
result = cpa.run()

print(f"Best key byte guess: 0x{result.best_guess:02X}")
print(f"Correlation: {result.correlation:.4f}")

# Attack all 16 bytes
full_key = []
for i in range(16):
    cpa = LascarCPA(session, byte_index=i)
    result = cpa.run()
    full_key.append(result.best_guess)

print(f"Recovered key: {bytes(full_key).hex()}")
```

### 4. BlackPill Test Target

```python
from slab_hw import BlackPillTarget, BlackPillConfig

# Connect to BlackPill test target
target = BlackPillTarget(port="/dev/ttyACM0")
target.connect()

# Configure target for glitch testing
config = BlackPillConfig(
    trigger_pin="PA0",           # Pin that triggers glitch controller
    trigger_polarity="rising",
    target_function=0x08001234,  # Function to test
    timeout_ms=100
)
target.configure(config)

# Run target and wait for trigger output
target.reset()
target.run()

# Check if target survived glitch
result = target.check_response()
if result.success:
    print(f"Target responded correctly: {result.data.hex()}")
elif result.timeout:
    print("Target crashed or hung")
else:
    print(f"Target returned unexpected data: {result.data.hex()}")

# Loop for glitch parameter search
def run_glitch_test(glitch_controller):
    """Run single glitch test iteration."""
    target.reset()
    target.run()                    # This triggers the glitch controller
    result = target.check_response()
    return result

# Use with external glitch controller (ChipWhisperer, etc.)
from slab_hw import create_cw_interface

cw = create_cw_interface()
cw.scope.glitch.configure(width=10, offset=500, repeat=1)

for width in range(5, 50, 5):
    for offset in range(100, 2000, 50):
        cw.scope.glitch.width = width
        cw.scope.glitch.offset = offset
        cw.arm()
        result = run_glitch_test(cw)
        if result.glitched:
            print(f"SUCCESS: width={width}, offset={offset}")
```

### 5. LaseStudio Laser Fault Injection

```python
from slab_hw import create_laser_controller, LaserSpot, LaserScan

# Connect to LaseStudio
laser = create_laser_controller()
laser.connect()

# Configure laser spot
spot = LaserSpot(
    x=1500,      # X position in microns
    y=2000,      # Y position in microns
    power=80,    # Power percentage
    duration=10  # Duration in nanoseconds
)

# Fire single spot
laser.fire(spot)

# Define scan pattern
scan = LaserScan(
    x_range=(1000, 2000),
    y_range=(1500, 2500),
    step=50,           # 50 micron step
    power=75,
    duration=10
)

# Run automated scan
for spot in scan:
    laser.fire(spot)
    if check_target_glitched():
        print(f"Found vulnerable spot: ({spot.x}, {spot.y})")
```

### 6. Avatar2-Compatible API

```python
from slab_hw import Avatar2Bridge, HILConfig, TargetType

# Avatar2-style configuration
config = HILConfig(
    target_type=TargetType.OPENOCD,
    openocd_config="stm32f4x.cfg",
    memory_map={
        "flash": (0x08000000, 0x100000),
        "sram":  (0x20000000, 0x20000),
    }
)

# Create Avatar2-compatible bridge
avatar = Avatar2Bridge(config)

# Add and configure target
target = avatar.add_target("stm32", TargetType.OPENOCD)
target.init_state = "halted"

# Initialize system
avatar.init_targets()

# Use familiar Avatar2 API
target.write_memory(0x20000000, 4, b"TEST")
data = target.read_memory(0x20000000, 4)
print(f"Memory: {data}")

# Set breakpoint and run
target.set_breakpoint(0x08001000)
target.cont()
target.wait()

# Cleanup
avatar.shutdown()
```

### 7. Compare Emulated vs Hardware Results

```python
from slab_hw import HardwareEmulatorBridge, TraceComparator
from slab_sidechannels import FastCPA

# Collect hardware traces
hw_bridge = HardwareEmulatorBridge()
hw_bridge.setup_hardware(platform="chipwhisperer")
hw_traces = hw_bridge.collect_traces(count=1000)

# Collect emulated traces
hw_bridge.setup_emulator(binary="firmware.elf")
emu_traces = hw_bridge.collect_emulated_traces(count=1000)

# Compare traces
comparator = TraceComparator(hw_traces, emu_traces)
correlation = comparator.compute_correlation()
print(f"HW/Emulator correlation: {correlation:.4f}")

# Run CPA on both and compare
hw_cpa = FastCPA(hw_traces.traces, hw_traces.plaintexts)
hw_key = hw_cpa.attack()

emu_cpa = FastCPA(emu_traces.traces, emu_traces.plaintexts)
emu_key = emu_cpa.attack()

print(f"HW recovered key:  {hw_key.hex()}")
print(f"EMU recovered key: {emu_key.hex()}")
print(f"Keys match: {hw_key == emu_key}")
```

## Supported Hardware

| Platform | Capabilities | Notes |
|----------|-------------|-------|
| ChipWhisperer Lite | Power analysis, Glitching | USB connection |
| ChipWhisperer Pro | Power analysis, Glitching, EMFI | USB connection |
| ChipWhisperer Husky | High-speed capture | USB connection |
| BlackPill (STM32F4) | Glitch/SCA test target | Slab test firmware |
| Lascar | Power trace acquisition | Ledger hardware |
| LaseStudio | Laser fault injection | Ledger hardware |
| OpenOCD | Debug/HIL testing | JTAG/SWD probes |
| J-Link | Debug/HIL testing | Segger probes |

## References

### Hardware Attack Platforms

- **ChipWhisperer**
  - O'Flynn & Chen, "ChipWhisperer: An Open-Source Platform for Hardware Embedded Security Research", COSADE 2014
  - [DOI: 10.1007/978-3-319-10175-0_17](https://doi.org/10.1007/978-3-319-10175-0_17)

- **Hardware-in-the-Loop Testing**
  - Muench et al., "Avatar2: A Multi-target Orchestration Platform", BAR 2018
  - [Paper](https://www.bar2018.dcs.gla.ac.uk/muench_bar18.pdf)

### Notable CVEs

- **CVE-2017-7932**: XTS-AES hardware timing attack
- **CVE-2019-9836**: AMD SEV memory encryption attack
- **CVE-2020-13777**: GnuTLS session ticket bypass
- **CVE-2021-30747**: Apple M1 PACMAN speculation attack

### Related Tools

- [ChipWhisperer](https://github.com/newaetech/chipwhisperer) - Open-source SCA/FI platform
- [Avatar2](https://github.com/avatartwo/avatar2) - Multi-target orchestration
- [OpenOCD](https://openocd.org/) - Open On-Chip Debugger
- [PyLink](https://github.com/square/pylink) - J-Link Python interface

## Author

Mathieu Renard <mathieu.renard@twistedwires.io>

## License

GPL-2.0-or-later
