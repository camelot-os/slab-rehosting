# Slab RP2350 - Raspberry Pi Pico 2 Support

Timing models, TrustZone emulation, secure boot analysis, and peripheral emulation for the RP2350 microcontroller (Raspberry Pi Pico 2).

## Features

- **Dual Architecture**: Cortex-M33 (TrustZone) OR Hazard3 RISC-V (switchable)
- **TrustZone Model**: SAU configuration, security boundaries, violation detection
- **Secure Boot Analysis**: OTP keys, boot chain verification, glitch simulation
- **Timing Models**: Both M33 and Hazard3 with crypto accelerator timing

## Quick Start

### 1. Basic Timing (Cortex-M33)

```python
from slab_rp2350 import RP2350Timing, CortexM33Timing

# Create timing model at 150MHz (default)
timing = RP2350Timing(frequency=150_000_000, architecture="cortex-m33")

# M33 has single-cycle multiply (vs 32 cycles on M0+!)
m33 = timing.get_core(0)
mul_cycles = m33.get_instruction_cycles("mul")
print(f"MUL: {mul_cycles} cycle (single-cycle on M33!)")

# Hardware divide
div_cycles = m33.get_instruction_cycles("udiv")
print(f"UDIV: {div_cycles} cycles (2-12, early termination)")

# DSP instructions
qadd_cycles = m33.get_instruction_cycles("qadd")
print(f"QADD: {qadd_cycles} cycle")
```

### 2. Hazard3 RISC-V Timing

```python
from slab_rp2350 import RP2350Timing, Hazard3Timing

# Switch to RISC-V mode
timing = RP2350Timing(architecture="hazard3")
rv = timing.get_core(0)

# Bit manipulation extensions
sh1add = rv.get_instruction_cycles("sh1add")  # Zba
clz = rv.get_instruction_cycles("clz")        # Zbb
bset = rv.get_instruction_cycles("bset")      # Zbs
pack = rv.get_instruction_cycles("pack")      # Zbkb (crypto)

print(f"sh1add: {sh1add}, clz: {clz}, bset: {bset}, pack: {pack}")
```

### 3. TrustZone Configuration

```python
from slab_rp2350 import TrustZoneModel, SAURegion, SAURegionType, SecurityState

tz = TrustZoneModel()

# Configure SAU regions
tz.configure_sau_region(
    index=0,
    base=0x10000000,     # Flash start
    limit=0x1003FFFF,    # First 256KB secure
    region_type=SAURegionType.SECURE
)

tz.configure_sau_region(
    index=1,
    base=0x1003F000,     # NSC region (4KB)
    limit=0x1003FFFF,
    region_type=SAURegionType.NSC
)

tz.configure_sau_region(
    index=2,
    base=0x10040000,     # Rest of flash non-secure
    limit=0x13FFFFFF,
    region_type=SAURegionType.NON_SECURE
)

# Check access from Non-Secure state
tz.current_state = SecurityState.NON_SECURE

# This will succeed (NS accessing NS region)
allowed = tz.check_access(0x10100000, is_write=False)
print(f"NS read from NS flash: {allowed}")

# This will fail (NS accessing S region)
allowed = tz.check_access(0x10000000, is_write=False)
print(f"NS read from S flash: {allowed}")  # False + violation logged
print(f"Violations: {tz.violations}")
```

### 4. Secure Boot Analysis

```python
from slab_rp2350 import SecureBootChain, OTPModel
import hashlib

# Create secure boot model
otp = OTPModel()
boot_chain = SecureBootChain(otp=otp)

# Simulate programming a boot key
valid_boot2 = b"valid_boot2_code" + b"\x00" * (256 - 16)
boot2_hash = hashlib.sha256(valid_boot2).digest()

# Program key into OTP slot 0
otp.set_boot_key(0, boot2_hash)

# Set boot flags
otp.write_row(0x080, 0x11)  # secure_boot_enable + key0_valid

# Verify valid BOOT2
result = boot_chain.verify_boot2(valid_boot2)
print(f"Valid BOOT2 verification: {result}")

# Try invalid BOOT2
invalid_boot2 = b"invalid_code" + b"\x00" * 244
result = boot_chain.verify_boot2(invalid_boot2)
print(f"Invalid BOOT2 verification: {result}")
print(f"Boot log: {boot_chain.boot_log}")
```

### 5. Glitch Attack Simulation

```python
from slab_rp2350 import SecureBootChain, OTPModel

otp = OTPModel()
boot_chain = SecureBootChain(otp=otp)

# Configure secure boot
otp.write_row(0x080, 0x11)  # Enable + key0 valid
otp.set_boot_key(0, b"\x00" * 32)  # Some key

# Simulate glitch attack on verification
attack_result = boot_chain.simulate_glitch_attack("verify_boot2")
print(f"Glitch attack success: {attack_result['success']}")
print(f"Details: {attack_result['details']}")
```

### 6. OTP Security Analysis

```python
from slab_rp2350 import OTPModel

otp = OTPModel()

# Program device secrets
otp.write_row(0, 0xDEADBEEF)
otp.write_row(1, 0xCAFEBABE)

# Lock against reprogramming
otp.lock_row(0)
otp.lock_row(1)

# Read-lock against non-secure access
otp.read_lock_row(0)
otp.read_lock_row(1)

# Secure read succeeds
secure_read = otp.read_row(0, secure=True)
print(f"Secure read: 0x{secure_read:08X}")

# Non-secure read fails
ns_read = otp.read_row(0, secure=False)
print(f"Non-secure read: {ns_read}")  # None
```

### 7. SHA-256 Accelerator Timing

```python
from slab_rp2350 import RP2350Timing

timing = RP2350Timing()

# Estimate cycles for hashing firmware
firmware_size = 64 * 1024  # 64KB
sha_cycles = timing.estimate_sha256_cycles(firmware_size)
sha_time_us = timing.cycles_to_us(sha_cycles)

print(f"SHA-256 of 64KB: {sha_cycles} cycles ({sha_time_us:.1f} us)")
```

### 8. Secure Function Call Overhead

```python
from slab_rp2350 import RP2350Timing

timing = RP2350Timing(architecture="cortex-m33")

# Estimate overhead of calling secure crypto function
crypto_function_cycles = 1000  # Example function
total_cycles = timing.estimate_secure_function_call(crypto_function_cycles)

print(f"Secure function call overhead: {total_cycles - crypto_function_cycles} cycles")
print(f"Total: {total_cycles} cycles ({timing.cycles_to_us(total_cycles):.2f} us)")
```

## Key Timing Differences: M33 vs M0+

| Operation | Cortex-M0+ | Cortex-M33 | Notes |
|-----------|------------|------------|-------|
| MUL | 32 cycles | 1 cycle | M33 has single-cycle multiplier |
| UDIV/SDIV | N/A | 2-12 cycles | M0+ has no hardware divide |
| DSP (QADD) | N/A | 1 cycle | M33 has DSP extension |
| FPU (VADD) | N/A | 1 cycle | M33 has FPU |
| Branch penalty | 2 cycles | 1 cycle | M33 has branch prediction |

## TrustZone Security Model

| Component | Description |
|-----------|-------------|
| SAU | Security Attribution Unit (8 regions) |
| IDAU | Implementation-Defined Attribution |
| SG | Secure Gateway instruction |
| BXNS | Branch to Non-Secure |
| NSC | Non-Secure Callable region |

## Secure Boot Stages

| Stage | Location | Max Size | Verification |
|-------|----------|----------|--------------|
| ROM_BOOT | ROM | 32KB | Hardware (immutable) |
| BOOT2 | Flash | 256 bytes | SHA-256 vs OTP key |
| APPLICATION | Flash | Flash size | Optional |

## Attack Surfaces

- **Fault Injection**: Glitch secure boot verification
- **TrustZone Bypass**: Exploit SAU misconfiguration
- **OTP Readout**: Bypass read protection
- **Side Channel**: Timing/power on crypto operations
- **Debug Port**: If not disabled in OTP

## References

- [RP2350 Datasheet](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf)
- [ARM Cortex-M33 TRM](https://developer.arm.com/documentation/100230)
- [ARM TrustZone for ARMv8-M](https://developer.arm.com/documentation/100690)

## License

GPL-2.0-or-later
