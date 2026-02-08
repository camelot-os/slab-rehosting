"""
Slab CI - Configuration Module

Defines schemas for test targets, vulnerable regions, and project configurations.
Users can specify which interfaces to test and which code sections are
expected to be vulnerable to various attacks.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from enum import Enum, auto
import json
import yaml
from pathlib import Path


class AttackType(Enum):
    """Types of security tests."""
    FUZZING = "fuzzing"
    SIDE_CHANNEL_CPA = "side_channel_cpa"
    SIDE_CHANNEL_DPA = "side_channel_dpa"
    SIDE_CHANNEL_TIMING = "side_channel_timing"
    FAULT_VOLTAGE = "fault_voltage"
    FAULT_CLOCK = "fault_clock"
    FAULT_EMFI = "fault_emfi"
    FAULT_LASER = "fault_laser"


class InterfaceType(Enum):
    """Communication interfaces for testing."""
    UART = "uart"
    SPI = "spi"
    I2C = "i2c"
    USB = "usb"
    JTAG = "jtag"
    SWD = "swd"
    CAN = "can"
    ETHERNET = "ethernet"
    CUSTOM = "custom"


class SeverityLevel(Enum):
    """Vulnerability severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class InterfaceConfig:
    """Configuration for a communication interface."""
    type: InterfaceType
    name: str
    enabled: bool = True

    # Interface-specific settings
    baudrate: int = 115200      # For UART
    frequency: int = 1000000    # For SPI/I2C
    address: int = 0            # For I2C slave address
    port: int = 0               # For TCP/UDP

    # Test settings
    fuzz_enabled: bool = True
    fuzz_seed: bytes = b""
    fuzz_iterations: int = 10000

    # Protocol settings
    protocol: str = ""          # Custom protocol name
    command_prefix: bytes = b""
    response_terminator: bytes = b"\r\n"


@dataclass
class VulnerableRegion:
    """
    Defines a code region expected to be vulnerable to specific attacks.

    Users can mark sections of code that should be tested for vulnerabilities.
    This helps focus testing and validates that protections are working.
    """
    name: str
    description: str = ""

    # Location
    start_address: int = 0
    end_address: int = 0
    function_name: str = ""     # Alternative to addresses
    source_file: str = ""
    source_line: int = 0

    # Vulnerability type
    attack_types: List[AttackType] = field(default_factory=list)
    expected_severity: SeverityLevel = SeverityLevel.HIGH

    # Glitch parameters (if applicable)
    glitch_offset_min: int = 0
    glitch_offset_max: int = 100
    glitch_width: int = 1

    # Side-channel parameters (if applicable)
    sensitive_data_offset: int = 0
    sensitive_data_size: int = 16
    key_byte_index: int = -1    # -1 = all bytes

    # Expected outcome
    expect_vulnerable: bool = True  # Should this region be found vulnerable?
    countermeasures: List[str] = field(default_factory=list)

    # Testing settings
    test_enabled: bool = True
    min_traces: int = 1000      # For side-channel
    min_attempts: int = 100     # For fault injection

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "start_address": f"0x{self.start_address:08X}",
            "end_address": f"0x{self.end_address:08X}",
            "function_name": self.function_name,
            "attack_types": [at.value for at in self.attack_types],
            "expected_severity": self.expected_severity.value,
            "expect_vulnerable": self.expect_vulnerable,
            "countermeasures": self.countermeasures,
        }


@dataclass
class TestTarget:
    """
    Configuration for a test target (firmware/device).

    Defines what to test, which interfaces to use, and expected vulnerabilities.
    """
    name: str
    description: str = ""
    version: str = "1.0"

    # Firmware
    firmware_path: str = ""
    firmware_base: int = 0x08000000
    elf_path: str = ""          # For symbols

    # Hardware
    device_type: str = "cortex-m4"
    clock_hz: int = 168000000
    flash_size: int = 0x100000
    ram_size: int = 0x40000

    # Interfaces to test
    interfaces: List[InterfaceConfig] = field(default_factory=list)

    # Vulnerable regions
    vulnerable_regions: List[VulnerableRegion] = field(default_factory=list)

    # Test settings
    enabled_attacks: List[AttackType] = field(default_factory=lambda: [
        AttackType.FUZZING,
        AttackType.SIDE_CHANNEL_CPA,
        AttackType.FAULT_VOLTAGE,
    ])

    # Timeouts
    execution_timeout_ms: int = 5000
    total_timeout_minutes: int = 60

    # Notifications
    notify_on_success: bool = False
    notify_on_failure: bool = True
    notify_on_new_vulnerability: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "firmware_path": self.firmware_path,
            "device_type": self.device_type,
            "interfaces": [
                {"type": i.type.value, "name": i.name, "enabled": i.enabled}
                for i in self.interfaces
            ],
            "vulnerable_regions": [vr.to_dict() for vr in self.vulnerable_regions],
            "enabled_attacks": [at.value for at in self.enabled_attacks],
        }


@dataclass
class TestConfig:
    """Configuration for a single test run."""
    target: TestTarget
    run_id: str = ""

    # Attack selection
    attacks: List[AttackType] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)  # Region names, empty = all

    # Parameters
    fuzz_iterations: int = 10000
    trace_count: int = 5000
    glitch_attempts: int = 1000

    # Options
    parallel_jobs: int = 1
    save_traces: bool = True
    save_crashes: bool = True
    generate_report: bool = True

    # Output
    output_dir: str = "results"
    report_format: str = "json"


@dataclass
class ProjectConfig:
    """
    Project-level configuration.

    Defines all targets, default settings, and organizational structure.
    """
    name: str
    description: str = ""
    version: str = "1.0"

    # Targets
    targets: List[TestTarget] = field(default_factory=list)

    # Default settings
    default_fuzz_iterations: int = 10000
    default_trace_count: int = 5000
    default_glitch_attempts: int = 1000

    # Schedule
    schedule_cron: str = ""     # e.g., "0 2 * * *" for nightly
    schedule_on_push: bool = True
    schedule_on_pr: bool = True

    # Notifications
    notification_emails: List[str] = field(default_factory=list)
    slack_webhook: str = ""
    n8n_webhook: str = ""

    # Pandadoc
    pandadoc_enabled: bool = False
    pandadoc_template_id: str = ""

    # Repository
    repository_url: str = ""
    branch: str = "main"

    @classmethod
    def from_yaml(cls, path: str) -> "ProjectConfig":
        """Load configuration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls._from_dict(data)

    @classmethod
    def from_json(cls, path: str) -> "ProjectConfig":
        """Load configuration from JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> "ProjectConfig":
        """Create from dictionary."""
        targets = []
        for t in data.get("targets", []):
            interfaces = [
                InterfaceConfig(
                    type=InterfaceType(i["type"]),
                    name=i["name"],
                    enabled=i.get("enabled", True),
                    baudrate=i.get("baudrate", 115200),
                )
                for i in t.get("interfaces", [])
            ]

            regions = [
                VulnerableRegion(
                    name=r["name"],
                    description=r.get("description", ""),
                    start_address=int(r.get("start_address", "0"), 0),
                    end_address=int(r.get("end_address", "0"), 0),
                    function_name=r.get("function_name", ""),
                    attack_types=[AttackType(at) for at in r.get("attack_types", [])],
                    expect_vulnerable=r.get("expect_vulnerable", True),
                )
                for r in t.get("vulnerable_regions", [])
            ]

            target = TestTarget(
                name=t["name"],
                description=t.get("description", ""),
                firmware_path=t.get("firmware_path", ""),
                device_type=t.get("device_type", "cortex-m4"),
                interfaces=interfaces,
                vulnerable_regions=regions,
                enabled_attacks=[AttackType(at) for at in t.get("enabled_attacks", [])],
            )
            targets.append(target)

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            targets=targets,
            default_fuzz_iterations=data.get("default_fuzz_iterations", 10000),
            default_trace_count=data.get("default_trace_count", 5000),
            schedule_cron=data.get("schedule_cron", ""),
            notification_emails=data.get("notification_emails", []),
            slack_webhook=data.get("slack_webhook", ""),
            n8n_webhook=data.get("n8n_webhook", ""),
        )

    def to_yaml(self, path: str) -> None:
        """Save configuration to YAML file."""
        data = self._to_dict()
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def to_json(self, path: str) -> None:
        """Save configuration to JSON file."""
        data = self._to_dict()
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "targets": [t.to_dict() for t in self.targets],
            "default_fuzz_iterations": self.default_fuzz_iterations,
            "default_trace_count": self.default_trace_count,
            "schedule_cron": self.schedule_cron,
            "notification_emails": self.notification_emails,
            "slack_webhook": self.slack_webhook,
            "n8n_webhook": self.n8n_webhook,
        }


# Example configuration template
EXAMPLE_CONFIG = """
# Slab CI Security Testing Configuration
# =======================================

name: "STM32 Glitch Target"
description: "Security analysis for STM32F405 glitch challenge"
version: "1.0"

targets:
  - name: "password_check"
    description: "Password verification bypass test"
    firmware_path: "firmware/stm32_glitch_target.bin"
    device_type: "cortex-m4"

    interfaces:
      - type: "uart"
        name: "serial"
        enabled: true
        baudrate: 115200

    vulnerable_regions:
      - name: "password_compare"
        description: "Password comparison loop"
        function_name: "test_password"
        start_address: "0x08000300"
        end_address: "0x08000350"
        attack_types:
          - "fault_voltage"
          - "side_channel_timing"
        expect_vulnerable: true
        glitch_offset_min: 40
        glitch_offset_max: 60

      - name: "signature_verify"
        description: "Signature verification"
        function_name: "test_signature"
        attack_types:
          - "fault_voltage"
          - "side_channel_cpa"
        expect_vulnerable: true

    enabled_attacks:
      - "fuzzing"
      - "fault_voltage"
      - "side_channel_timing"

default_fuzz_iterations: 10000
default_trace_count: 5000
default_glitch_attempts: 1000

schedule_cron: "0 2 * * *"  # Nightly at 2 AM
schedule_on_push: true
schedule_on_pr: true

notification_emails:
  - "security-team@example.com"

slack_webhook: ""
n8n_webhook: ""
pandadoc_enabled: false
"""


def create_example_config(path: str = "slab-ci.yaml") -> None:
    """Create an example configuration file."""
    with open(path, "w") as f:
        f.write(EXAMPLE_CONFIG)
    print(f"Created example configuration: {path}")
