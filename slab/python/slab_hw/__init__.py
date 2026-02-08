"""
Slab HW - Hardware Attack Interface Module

Provides interfaces for real hardware attack platforms:
- Lascar: Side-channel trace acquisition (Ledger)
- LaseStudio: Laser fault injection (Ledger)
- BlackPill: STM32F4-based glitch controller
- ChipWhisperer: NewAE Technology platform

This module bridges emulated attacks (slab_glitch) with real hardware,
enabling comparison studies and validation of emulation models.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.1.0"
__author__ = "Mathieu Renard"
__project__ = "Slab"

# Lazy imports to avoid circular dependencies and missing modules
def __getattr__(name):
    """Lazy import mechanism for optional components."""
    _exports = {
        # Base classes
        "HardwarePlatform": (".base", "HardwarePlatform"),
        "TraceAcquisition": (".base", "TraceAcquisition"),
        "GlitchController": (".base", "GlitchController"),
        "LaserController": (".base", "LaserController"),
        "PlatformCapabilities": (".base", "PlatformCapabilities"),
        "HardwareConfig": (".base", "HardwareConfig"),
        # Lascar integration
        "LascarSession": (".lascar_interface", "LascarSession"),
        "LascarTraceSet": (".lascar_interface", "LascarTraceSet"),
        "LascarEngine": (".lascar_interface", "LascarEngine"),
        "LascarCPA": (".lascar_interface", "LascarCPA"),
        "LascarDPA": (".lascar_interface", "LascarDPA"),
        "create_lascar_session": (".lascar_interface", "create_lascar_session"),
        # LaseStudio integration
        "LaseStudioController": (".lasestudio_interface", "LaseStudioController"),
        "LaserSpot": (".lasestudio_interface", "LaserSpot"),
        "LaserScan": (".lasestudio_interface", "LaserScan"),
        "LaserTiming": (".lasestudio_interface", "LaserTiming"),
        "create_laser_controller": (".lasestudio_interface", "create_laser_controller"),
        # BlackPill glitch controller
        "BlackPillGlitcher": (".blackpill", "BlackPillGlitcher"),
        "BlackPillConfig": (".blackpill", "BlackPillConfig"),
        "GlitchWaveform": (".blackpill", "GlitchWaveform"),
        "TriggerConfig": (".blackpill", "TriggerConfig"),
        "create_blackpill_glitcher": (".blackpill", "create_blackpill_glitcher"),
        # ChipWhisperer integration
        "ChipWhispererInterface": (".chipwhisperer_interface", "ChipWhispererInterface"),
        "CWScope": (".chipwhisperer_interface", "CWScope"),
        "CWTarget": (".chipwhisperer_interface", "CWTarget"),
        "create_cw_interface": (".chipwhisperer_interface", "create_cw_interface"),
        # Comparison framework
        "HardwareEmulatorBridge": (".bridge", "HardwareEmulatorBridge"),
        "ComparisonResult": (".bridge", "ComparisonResult"),
        "TraceComparator": (".bridge", "TraceComparator"),
        # Standalone HIL (no external dependencies)
        "HILBridge": (".hil", "HILBridge"),
        "HILConfiguration": (".hil", "HILConfiguration"),
        "HardwareTarget": (".hil", "HardwareTarget"),
        "GDBTarget": (".hil", "GDBTarget"),
        "SimulationTarget": (".hil", "SimulationTarget"),
        "DebuggerType": (".hil", "DebuggerType"),
        "TargetState": (".hil", "TargetState"),
        "MemoryRegion": (".hil", "MemoryRegion"),
        # Avatar2-compatible API (uses standalone HIL internally)
        "Avatar2Bridge": (".avatar2_hil", "Avatar2Bridge"),
        "HILConfig": (".avatar2_hil", "HILConfig"),
        "HILGlitchController": (".avatar2_hil", "HILGlitchController"),
        "MemoryRange": (".avatar2_hil", "MemoryRange"),
        "TargetType": (".avatar2_hil", "TargetType"),
    }

    if name in _exports:
        module_name, attr_name = _exports[name]
        import importlib
        module = importlib.import_module(module_name, __package__)
        return getattr(module, attr_name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__project__",
    # Base classes
    "HardwarePlatform",
    "TraceAcquisition",
    "GlitchController",
    "LaserController",
    "PlatformCapabilities",
    "HardwareConfig",
    # Lascar integration
    "LascarSession",
    "LascarTraceSet",
    "LascarEngine",
    "LascarCPA",
    "LascarDPA",
    "create_lascar_session",
    # LaseStudio integration
    "LaseStudioController",
    "LaserSpot",
    "LaserScan",
    "LaserTiming",
    "create_laser_controller",
    # BlackPill glitch controller
    "BlackPillGlitcher",
    "BlackPillConfig",
    "GlitchWaveform",
    "TriggerConfig",
    "create_blackpill_glitcher",
    # ChipWhisperer integration
    "ChipWhispererInterface",
    "CWScope",
    "CWTarget",
    "create_cw_interface",
    # Comparison framework
    "HardwareEmulatorBridge",
    "ComparisonResult",
    "TraceComparator",
    # Standalone HIL (no external dependencies)
    "HILBridge",
    "HILConfiguration",
    "HardwareTarget",
    "GDBTarget",
    "SimulationTarget",
    "DebuggerType",
    "TargetState",
    "MemoryRegion",
    # Avatar2-compatible API
    "Avatar2Bridge",
    "HILConfig",
    "HILGlitchController",
    "MemoryRange",
    "TargetType",
]
