"""
Slab CI - Firmware Analyzer

Automatic firmware analysis and test configuration discovery.
Designed to work with LLMs and integrate with Capstone/IDA/Binary Ninja MCP.

Features:
- Binary structure analysis (ELF, raw binary, Intel HEX)
- Automatic disassembly with Capstone
- Function identification and classification
- Vulnerable region detection (crypto, auth, loop patterns)
- Interface discovery (UART, SPI, I2C)
- LLM-friendly output for assisted configuration
- MCP integration for IDA/Binary Ninja

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import struct
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum, auto
from pathlib import Path
import re
import json


class ArchType(Enum):
    """CPU architecture types."""
    ARM_CORTEX_M = "arm_cortex_m"
    ARM_CORTEX_A = "arm_cortex_a"
    ARM_THUMB = "arm_thumb"
    MIPS = "mips"
    RISCV = "riscv"
    X86 = "x86"
    UNKNOWN = "unknown"


class FunctionType(Enum):
    """Function classification types."""
    UNKNOWN = "unknown"
    CRYPTO_AES = "crypto_aes"
    CRYPTO_SHA = "crypto_sha"
    CRYPTO_RSA = "crypto_rsa"
    CRYPTO_ECC = "crypto_ecc"
    AUTH_PASSWORD = "auth_password"
    AUTH_SIGNATURE = "auth_signature"
    AUTH_TOKEN = "auth_token"
    UART_TX = "uart_tx"
    UART_RX = "uart_rx"
    SPI_XFER = "spi_transfer"
    I2C_XFER = "i2c_transfer"
    GPIO_READ = "gpio_read"
    GPIO_WRITE = "gpio_write"
    DELAY_LOOP = "delay_loop"
    INFINITE_LOOP = "infinite_loop"
    MEMORY_COPY = "memory_copy"
    BOOT_INIT = "boot_init"
    INTERRUPT_HANDLER = "interrupt_handler"


@dataclass
class DisassembledFunction:
    """Disassembled function information."""
    name: str
    start_address: int
    end_address: int
    size: int
    instructions: List[Dict[str, Any]] = field(default_factory=list)

    # Classification
    function_type: FunctionType = FunctionType.UNKNOWN
    confidence: float = 0.0

    # Analysis
    has_loops: bool = False
    has_branches: bool = False
    calls_functions: List[int] = field(default_factory=list)
    called_by: List[int] = field(default_factory=list)
    accesses_addresses: List[int] = field(default_factory=list)

    # Vulnerability indicators
    potential_vulnerabilities: List[str] = field(default_factory=list)
    recommended_tests: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "start_address": f"0x{self.start_address:08X}",
            "end_address": f"0x{self.end_address:08X}",
            "size": self.size,
            "function_type": self.function_type.value,
            "confidence": self.confidence,
            "has_loops": self.has_loops,
            "has_branches": self.has_branches,
            "potential_vulnerabilities": self.potential_vulnerabilities,
            "recommended_tests": self.recommended_tests,
        }


@dataclass
class MemoryRegion:
    """Memory region information."""
    name: str
    start: int
    end: int
    permissions: str = "rwx"
    type: str = "unknown"  # flash, ram, peripheral


@dataclass
class FirmwareInfo:
    """Complete firmware analysis information."""
    path: str
    size: int
    architecture: ArchType = ArchType.UNKNOWN
    entry_point: int = 0
    load_address: int = 0

    # Regions
    memory_regions: List[MemoryRegion] = field(default_factory=list)

    # Functions
    functions: List[DisassembledFunction] = field(default_factory=list)

    # Strings found
    strings: List[Tuple[int, str]] = field(default_factory=list)

    # Detected interfaces
    interfaces: Dict[str, Any] = field(default_factory=dict)

    # Symbols (if ELF)
    symbols: Dict[str, int] = field(default_factory=dict)

    # LLM analysis suggestions
    llm_prompts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "path": self.path,
            "size": self.size,
            "architecture": self.architecture.value,
            "entry_point": f"0x{self.entry_point:08X}",
            "load_address": f"0x{self.load_address:08X}",
            "memory_regions": [
                {"name": r.name, "start": f"0x{r.start:08X}",
                 "end": f"0x{r.end:08X}", "type": r.type}
                for r in self.memory_regions
            ],
            "functions": [f.to_dict() for f in self.functions],
            "interfaces": self.interfaces,
            "symbols": {k: f"0x{v:08X}" for k, v in self.symbols.items()},
            "llm_prompts": self.llm_prompts,
        }


class FirmwareAnalyzer:
    """
    Automatic firmware analyzer.

    Analyzes firmware binaries to discover structure, functions,
    and potential vulnerable regions. Designed for LLM integration.

    Usage:
        analyzer = FirmwareAnalyzer()
        info = analyzer.analyze("firmware.bin")

        # Get LLM-friendly summary
        print(analyzer.describe_for_llm(info))

        # Generate test configuration
        config = analyzer.generate_test_config(info)
    """

    # Known peripheral addresses for ARM Cortex-M (STM32)
    KNOWN_PERIPHERALS = {
        (0x40000000, 0x40008000): "APB1",
        (0x40010000, 0x40015000): "APB2",
        (0x40020000, 0x40024000): "GPIO",
        (0x40023800, 0x40024000): "RCC",
        (0x40004400, 0x40004800): "USART2",
        (0x40011000, 0x40011400): "USART1",
        (0x40003800, 0x40003C00): "SPI2",
        (0x40013000, 0x40013400): "SPI1",
        (0x40005400, 0x40005800): "I2C1",
    }

    # Patterns for function identification
    CRYPTO_PATTERNS = [
        (r'aes|rijndael', FunctionType.CRYPTO_AES),
        (r'sha\d*|hash', FunctionType.CRYPTO_SHA),
        (r'rsa|pkcs', FunctionType.CRYPTO_RSA),
        (r'ecc|ecdsa|curve', FunctionType.CRYPTO_ECC),
    ]

    AUTH_PATTERNS = [
        (r'password|passwd|pwd|pin', FunctionType.AUTH_PASSWORD),
        (r'signature|verify|sign', FunctionType.AUTH_SIGNATURE),
        (r'token|jwt|bearer', FunctionType.AUTH_TOKEN),
    ]

    INTERFACE_PATTERNS = [
        (r'uart|serial|putc|getc', FunctionType.UART_TX),
        (r'spi.*xfer|spi.*send|spi.*recv', FunctionType.SPI_XFER),
        (r'i2c.*xfer|i2c.*read|i2c.*write', FunctionType.I2C_XFER),
        (r'gpio.*read|gpio.*get', FunctionType.GPIO_READ),
        (r'gpio.*write|gpio.*set', FunctionType.GPIO_WRITE),
    ]

    def __init__(self, use_capstone: bool = True):
        """Initialize analyzer."""
        self.use_capstone = use_capstone
        self._capstone = None

        if use_capstone:
            try:
                import capstone
                self._capstone = capstone
            except ImportError:
                print("Warning: Capstone not available. Install with: pip install capstone")
                self.use_capstone = False

    def analyze(
        self,
        firmware_path: str,
        arch: ArchType = ArchType.ARM_THUMB,
        load_address: int = 0x08000000,
    ) -> FirmwareInfo:
        """
        Analyze firmware binary.

        Args:
            firmware_path: Path to firmware file
            arch: CPU architecture
            load_address: Base address to load firmware

        Returns:
            FirmwareInfo with analysis results
        """
        path = Path(firmware_path)
        if not path.exists():
            raise FileNotFoundError(f"Firmware not found: {firmware_path}")

        data = path.read_bytes()

        info = FirmwareInfo(
            path=str(path),
            size=len(data),
            architecture=arch,
            load_address=load_address,
        )

        # Detect file type
        if data[:4] == b'\x7fELF':
            self._analyze_elf(data, info)
        elif data[:4] in (b':10', b':02'):  # Intel HEX
            self._analyze_ihex(data, info)
        else:
            self._analyze_raw(data, info, load_address)

        # Extract strings
        info.strings = self._extract_strings(data, load_address)

        # Disassemble and analyze
        if self.use_capstone and self._capstone:
            self._disassemble(data, info)
            self._analyze_functions(info)

        # Detect interfaces
        info.interfaces = self._detect_interfaces(info)

        # Generate LLM prompts
        info.llm_prompts = self._generate_llm_prompts(info)

        return info

    def _analyze_raw(self, data: bytes, info: FirmwareInfo, load_address: int) -> None:
        """Analyze raw binary."""
        info.load_address = load_address

        # Check for ARM vector table
        if len(data) >= 8:
            sp, entry = struct.unpack('<II', data[:8])
            if 0x20000000 <= sp <= 0x30000000:  # Valid SRAM range
                info.entry_point = entry & ~1  # Clear thumb bit
                info.memory_regions.append(MemoryRegion(
                    name="flash",
                    start=load_address,
                    end=load_address + len(data),
                    permissions="rx",
                    type="flash",
                ))

    def _analyze_elf(self, data: bytes, info: FirmwareInfo) -> None:
        """Analyze ELF file."""
        # Basic ELF parsing
        if data[4] == 1:  # 32-bit
            e_entry = struct.unpack('<I', data[0x18:0x1C])[0]
            info.entry_point = e_entry

            # Parse section headers for symbols
            e_shoff = struct.unpack('<I', data[0x20:0x24])[0]
            e_shnum = struct.unpack('<H', data[0x30:0x32])[0]
            e_shstrndx = struct.unpack('<H', data[0x32:0x34])[0]

    def _analyze_ihex(self, data: bytes, info: FirmwareInfo) -> None:
        """Analyze Intel HEX file."""
        # Parse Intel HEX records
        lines = data.decode('ascii', errors='ignore').split('\n')
        min_addr = 0xFFFFFFFF
        max_addr = 0

        for line in lines:
            if not line.startswith(':'):
                continue
            byte_count = int(line[1:3], 16)
            address = int(line[3:7], 16)
            record_type = int(line[7:9], 16)

            if record_type == 0:  # Data record
                min_addr = min(min_addr, address)
                max_addr = max(max_addr, address + byte_count)

        if min_addr < 0xFFFFFFFF:
            info.load_address = min_addr
            info.memory_regions.append(MemoryRegion(
                name="flash",
                start=min_addr,
                end=max_addr,
                type="flash",
            ))

    def _extract_strings(
        self, data: bytes, base: int, min_length: int = 4
    ) -> List[Tuple[int, str]]:
        """Extract printable strings from binary."""
        strings = []
        pattern = rb'[\x20-\x7e]{' + str(min_length).encode() + rb',}'

        for match in re.finditer(pattern, data):
            addr = base + match.start()
            string = match.group().decode('ascii', errors='replace')
            strings.append((addr, string))

        return strings[:500]  # Limit to 500 strings

    def _disassemble(self, data: bytes, info: FirmwareInfo) -> None:
        """Disassemble firmware using Capstone."""
        if not self._capstone:
            return

        cs = self._capstone

        # Set up disassembler based on architecture
        if info.architecture in (ArchType.ARM_THUMB, ArchType.ARM_CORTEX_M):
            md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
        elif info.architecture == ArchType.ARM_CORTEX_A:
            md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_ARM)
        else:
            return

        md.detail = True

        # Find function boundaries (heuristic)
        functions = self._find_functions(data, info.load_address, md)
        info.functions = functions

    def _find_functions(
        self,
        data: bytes,
        base: int,
        md,
    ) -> List[DisassembledFunction]:
        """Find functions in binary (heuristic)."""
        functions = []
        current_func = None
        func_id = 0

        # Disassemble from entry point
        start = 0
        if len(data) >= 8:
            # Skip vector table for ARM
            start = 0x100 if base >= 0x08000000 else 0

        for insn in md.disasm(data[start:], base + start):
            # Detect function prologue (push {lr} or similar)
            if insn.mnemonic == 'push' and 'lr' in insn.op_str:
                if current_func:
                    current_func.end_address = insn.address - 1
                    current_func.size = current_func.end_address - current_func.start_address
                    functions.append(current_func)

                func_id += 1
                current_func = DisassembledFunction(
                    name=f"func_{func_id:04d}",
                    start_address=insn.address,
                    end_address=insn.address,
                    size=0,
                )

            if current_func:
                # Record instruction
                current_func.instructions.append({
                    'address': insn.address,
                    'mnemonic': insn.mnemonic,
                    'op_str': insn.op_str,
                })

                # Detect loops
                if insn.mnemonic.startswith('b') and insn.op_str:
                    try:
                        target = int(insn.op_str.replace('#', ''), 16)
                        if target < insn.address:
                            current_func.has_loops = True
                    except ValueError:
                        pass

                # Detect branches
                if insn.mnemonic in ('beq', 'bne', 'blt', 'bgt', 'ble', 'bge'):
                    current_func.has_branches = True

                # Detect function calls
                if insn.mnemonic in ('bl', 'blx'):
                    try:
                        target = int(insn.op_str.replace('#', ''), 16)
                        current_func.calls_functions.append(target)
                    except ValueError:
                        pass

            # Limit analysis
            if len(functions) >= 200:
                break

        if current_func:
            functions.append(current_func)

        return functions

    def _analyze_functions(self, info: FirmwareInfo) -> None:
        """Analyze functions and classify them."""
        # Use symbol names if available
        symbol_addrs = {v: k for k, v in info.symbols.items()}

        # Use strings for hints
        string_addrs = {addr: s for addr, s in info.strings}

        for func in info.functions:
            # Check if we have a symbol
            if func.start_address in symbol_addrs:
                func.name = symbol_addrs[func.start_address]

            # Classify based on name
            name_lower = func.name.lower()

            for pattern, func_type in self.CRYPTO_PATTERNS:
                if re.search(pattern, name_lower):
                    func.function_type = func_type
                    func.confidence = 0.9
                    func.potential_vulnerabilities.append("Side-channel (power/timing)")
                    func.recommended_tests.extend(["side_channel_cpa", "side_channel_timing"])
                    break

            for pattern, func_type in self.AUTH_PATTERNS:
                if re.search(pattern, name_lower):
                    func.function_type = func_type
                    func.confidence = 0.8
                    func.potential_vulnerabilities.append("Fault injection bypass")
                    func.recommended_tests.extend(["fault_voltage", "fuzzing"])
                    break

            for pattern, func_type in self.INTERFACE_PATTERNS:
                if re.search(pattern, name_lower):
                    func.function_type = func_type
                    func.confidence = 0.8
                    break

            # Heuristic analysis for unnamed functions
            if func.function_type == FunctionType.UNKNOWN:
                # Check for loop patterns
                if func.has_loops and func.has_branches:
                    func.potential_vulnerabilities.append("Possible comparison loop")
                    func.recommended_tests.append("fault_voltage")

                # Check for peripheral access
                for insn in func.instructions:
                    if 'ldr' in insn['mnemonic'] or 'str' in insn['mnemonic']:
                        try:
                            # Check for peripheral addresses
                            addr_match = re.search(r'0x([0-9a-fA-F]+)', insn['op_str'])
                            if addr_match:
                                addr = int(addr_match.group(1), 16)
                                for (start, end), name in self.KNOWN_PERIPHERALS.items():
                                    if start <= addr < end:
                                        func.accesses_addresses.append(addr)
                        except (ValueError, AttributeError):
                            pass

    def _detect_interfaces(self, info: FirmwareInfo) -> Dict[str, Any]:
        """Detect communication interfaces used."""
        interfaces = {
            "uart": {"detected": False, "addresses": []},
            "spi": {"detected": False, "addresses": []},
            "i2c": {"detected": False, "addresses": []},
            "gpio": {"detected": False, "addresses": []},
        }

        # Check function types
        for func in info.functions:
            if func.function_type in (FunctionType.UART_TX, FunctionType.UART_RX):
                interfaces["uart"]["detected"] = True
            elif func.function_type == FunctionType.SPI_XFER:
                interfaces["spi"]["detected"] = True
            elif func.function_type == FunctionType.I2C_XFER:
                interfaces["i2c"]["detected"] = True
            elif func.function_type in (FunctionType.GPIO_READ, FunctionType.GPIO_WRITE):
                interfaces["gpio"]["detected"] = True

        # Check peripheral accesses
        for func in info.functions:
            for addr in func.accesses_addresses:
                if 0x40004400 <= addr < 0x40005000:  # USART
                    interfaces["uart"]["detected"] = True
                    interfaces["uart"]["addresses"].append(addr)
                elif 0x40003800 <= addr < 0x40004000 or 0x40013000 <= addr < 0x40013400:
                    interfaces["spi"]["detected"] = True
                    interfaces["spi"]["addresses"].append(addr)
                elif 0x40005400 <= addr < 0x40006000:
                    interfaces["i2c"]["detected"] = True
                    interfaces["i2c"]["addresses"].append(addr)
                elif 0x40020000 <= addr < 0x40024000:
                    interfaces["gpio"]["detected"] = True
                    interfaces["gpio"]["addresses"].append(addr)

        # Check strings
        for addr, s in info.strings:
            s_lower = s.lower()
            if 'uart' in s_lower or 'serial' in s_lower or 'baud' in s_lower:
                interfaces["uart"]["detected"] = True
            if 'spi' in s_lower:
                interfaces["spi"]["detected"] = True
            if 'i2c' in s_lower:
                interfaces["i2c"]["detected"] = True

        return interfaces

    def _generate_llm_prompts(self, info: FirmwareInfo) -> List[str]:
        """Generate prompts for LLM analysis."""
        prompts = []

        # Basic analysis prompt
        prompts.append(f"""
Analyze this ARM Cortex-M firmware:
- Size: {info.size} bytes
- Entry point: 0x{info.entry_point:08X}
- Functions found: {len(info.functions)}
- Architecture: {info.architecture.value}

Key questions:
1. What is the main purpose of this firmware?
2. What communication interfaces are used?
3. Which functions handle sensitive operations?
4. What potential vulnerabilities exist?
""".strip())

        # Crypto functions
        crypto_funcs = [f for f in info.functions
                       if f.function_type in (FunctionType.CRYPTO_AES, FunctionType.CRYPTO_SHA,
                                              FunctionType.CRYPTO_RSA, FunctionType.CRYPTO_ECC)]
        if crypto_funcs:
            prompts.append(f"""
Crypto functions detected ({len(crypto_funcs)}):
{chr(10).join(f'- {f.name} at 0x{f.start_address:08X} ({f.function_type.value})' for f in crypto_funcs)}

Analyze these for:
1. Side-channel vulnerability (power/timing)
2. Constant-time implementation
3. Key handling security
""".strip())

        # Auth functions
        auth_funcs = [f for f in info.functions
                     if f.function_type in (FunctionType.AUTH_PASSWORD, FunctionType.AUTH_SIGNATURE,
                                            FunctionType.AUTH_TOKEN)]
        if auth_funcs:
            prompts.append(f"""
Authentication functions detected ({len(auth_funcs)}):
{chr(10).join(f'- {f.name} at 0x{f.start_address:08X} ({f.function_type.value})' for f in auth_funcs)}

Analyze these for:
1. Fault injection vulnerability (skip check)
2. Timing attacks
3. Bypass opportunities
""".strip())

        # Unknown but suspicious functions
        suspicious = [f for f in info.functions
                     if f.has_loops and f.has_branches and f.function_type == FunctionType.UNKNOWN]
        if suspicious:
            prompts.append(f"""
Suspicious functions needing manual analysis ({len(suspicious[:10])}):
{chr(10).join(f'- {f.name} at 0x{f.start_address:08X} (loops+branches, {len(f.instructions)} instructions)' for f in suspicious[:10])}

These have loop and branch patterns typical of:
1. Comparison routines
2. Crypto operations
3. Verification checks
""".strip())

        return prompts

    def describe_for_llm(self, info: FirmwareInfo) -> str:
        """
        Generate comprehensive LLM-friendly description.

        Use this to provide context to an LLM for assisted analysis.
        """
        sections = [
            "=" * 60,
            "FIRMWARE ANALYSIS REPORT",
            "=" * 60,
            "",
            f"File: {info.path}",
            f"Size: {info.size} bytes ({info.size / 1024:.1f} KB)",
            f"Architecture: {info.architecture.value}",
            f"Entry Point: 0x{info.entry_point:08X}",
            f"Load Address: 0x{info.load_address:08X}",
            "",
        ]

        # Memory regions
        if info.memory_regions:
            sections.append("MEMORY REGIONS:")
            for r in info.memory_regions:
                sections.append(f"  {r.name}: 0x{r.start:08X}-0x{r.end:08X} ({r.type})")
            sections.append("")

        # Interfaces
        sections.append("DETECTED INTERFACES:")
        for name, data in info.interfaces.items():
            status = "YES" if data["detected"] else "NO"
            sections.append(f"  {name.upper()}: {status}")
        sections.append("")

        # Functions summary
        sections.append(f"FUNCTIONS FOUND: {len(info.functions)}")
        func_types = {}
        for f in info.functions:
            t = f.function_type.value
            func_types[t] = func_types.get(t, 0) + 1

        for t, count in sorted(func_types.items(), key=lambda x: -x[1]):
            sections.append(f"  {t}: {count}")
        sections.append("")

        # Potential vulnerabilities
        vuln_funcs = [f for f in info.functions if f.potential_vulnerabilities]
        if vuln_funcs:
            sections.append("POTENTIAL VULNERABILITIES:")
            for f in vuln_funcs[:20]:
                sections.append(f"  {f.name} (0x{f.start_address:08X}):")
                for v in f.potential_vulnerabilities:
                    sections.append(f"    - {v}")
            sections.append("")

        # Interesting strings
        interesting_strings = [
            s for s in info.strings
            if any(x in s[1].lower() for x in
                   ['password', 'key', 'secret', 'flag', 'auth', 'login', 'admin'])
        ]
        if interesting_strings:
            sections.append("INTERESTING STRINGS:")
            for addr, s in interesting_strings[:20]:
                sections.append(f"  0x{addr:08X}: {s[:60]}...")
            sections.append("")

        # LLM prompts
        sections.append("ANALYSIS PROMPTS FOR LLM:")
        for i, prompt in enumerate(info.llm_prompts, 1):
            sections.append(f"\n--- Prompt {i} ---")
            sections.append(prompt)

        return "\n".join(sections)

    def generate_test_config(
        self,
        info: FirmwareInfo,
        project_name: str = "auto_discovered",
    ) -> Dict[str, Any]:
        """
        Generate test configuration from analysis.

        Returns configuration that can be used with Slab CI.
        """
        from .config import (
            ProjectConfig, TestTarget, VulnerableRegion, InterfaceConfig,
            AttackType, InterfaceType
        )

        # Create interfaces
        interfaces = []
        if info.interfaces.get("uart", {}).get("detected"):
            interfaces.append(InterfaceConfig(
                type=InterfaceType.UART,
                name="uart0",
                enabled=True,
                baudrate=115200,
            ))
        if info.interfaces.get("spi", {}).get("detected"):
            interfaces.append(InterfaceConfig(
                type=InterfaceType.SPI,
                name="spi0",
                enabled=True,
            ))

        # Create vulnerable regions
        regions = []
        for func in info.functions:
            if func.potential_vulnerabilities:
                attacks = []
                for test in func.recommended_tests:
                    try:
                        attacks.append(AttackType(test))
                    except ValueError:
                        pass

                region = VulnerableRegion(
                    name=func.name,
                    description=", ".join(func.potential_vulnerabilities),
                    start_address=func.start_address,
                    end_address=func.end_address,
                    function_name=func.name,
                    attack_types=attacks,
                    expect_vulnerable=True,
                )
                regions.append(region)

        # Create target
        target = TestTarget(
            name=project_name,
            description=f"Auto-discovered from {info.path}",
            firmware_path=info.path,
            firmware_base=info.load_address,
            device_type="cortex-m4",
            interfaces=interfaces,
            vulnerable_regions=regions,
        )

        # Create project config
        config = ProjectConfig(
            name=project_name,
            description="Auto-generated configuration",
            targets=[target],
        )

        return config._to_dict()


# =============================================================================
# MCP Integration helpers
# =============================================================================

class MCPIntegration:
    """
    Integration helpers for IDA/Binary Ninja MCP.

    Provides methods to query external analysis tools via MCP.
    """

    @staticmethod
    def format_ida_query(info: FirmwareInfo) -> Dict[str, Any]:
        """Format query for IDA MCP."""
        return {
            "action": "analyze_firmware",
            "params": {
                "path": info.path,
                "base_address": info.load_address,
                "architecture": "arm:cortex-m",
                "requests": [
                    "list_functions",
                    "get_xrefs",
                    "find_crypto",
                    "find_strings",
                ]
            }
        }

    @staticmethod
    def format_binja_query(info: FirmwareInfo) -> Dict[str, Any]:
        """Format query for Binary Ninja MCP."""
        return {
            "action": "analyze",
            "params": {
                "file": info.path,
                "base": hex(info.load_address),
                "arch": "thumb2",
                "analysis": ["functions", "strings", "xrefs"]
            }
        }

    @staticmethod
    def parse_ida_response(response: Dict[str, Any], info: FirmwareInfo) -> None:
        """Parse IDA MCP response and update FirmwareInfo."""
        if "functions" in response:
            for func_data in response["functions"]:
                # Update or add function info
                for func in info.functions:
                    if func.start_address == func_data.get("address"):
                        func.name = func_data.get("name", func.name)
                        break

        if "symbols" in response:
            info.symbols.update(response["symbols"])
