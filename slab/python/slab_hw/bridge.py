"""
Slab HW - Hardware/Emulator Bridge

Provides comparison and validation between:
- Emulated attacks (slab_glitch, slab_sidechannels)
- Real hardware attacks (ChipWhisperer, BlackPill, LaseStudio)

This module enables:
- Validation of emulation model accuracy
- Correlation studies between simulated and real traces
- Transfer of attack parameters from emulation to hardware
- Automated regression testing

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass, field
from typing import (
    Optional, Dict, Any, Callable, List, Tuple, Union,
    Iterator, Protocol, TYPE_CHECKING
)
from enum import IntEnum, auto
from pathlib import Path
import numpy as np
import logging
import json
import time
from datetime import datetime

from .base import HardwarePlatform, HardwareConfig

logger = logging.getLogger(__name__)


class ComparisonMetric(IntEnum):
    """Metrics for comparing emulation vs hardware."""
    CORRELATION = 0         # Pearson correlation
    MSE = 1                 # Mean squared error
    DTW = 2                 # Dynamic time warping distance
    SUCCESS_RATE = 3        # Attack success rate
    TIMING_ACCURACY = 4     # Timing model accuracy
    LEAKAGE_DETECTION = 5   # T-test agreement


@dataclass
class ComparisonResult:
    """Result of comparing emulation with hardware."""
    metric: ComparisonMetric
    name: str = ""
    description: str = ""

    # Core results
    emulated_value: float = 0.0
    hardware_value: float = 0.0
    agreement: float = 0.0      # 0-1 agreement score

    # Statistical data
    correlation: float = 0.0
    mse: float = 0.0
    std_dev: float = 0.0

    # Metadata
    emulator_params: Dict[str, Any] = field(default_factory=dict)
    hardware_params: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    notes: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric.name,
            "name": self.name,
            "description": self.description,
            "emulated_value": self.emulated_value,
            "hardware_value": self.hardware_value,
            "agreement": self.agreement,
            "correlation": self.correlation,
            "mse": self.mse,
            "std_dev": self.std_dev,
            "emulator_params": self.emulator_params,
            "hardware_params": self.hardware_params,
            "timestamp": self.timestamp,
            "notes": self.notes,
        }

    def is_acceptable(self, threshold: float = 0.8) -> bool:
        """Check if agreement is above threshold."""
        return self.agreement >= threshold


class TraceComparator:
    """
    Compare power/EM traces between emulation and hardware.

    Provides correlation analysis, alignment, and statistical comparison.
    """

    def __init__(self):
        self._emulated_traces: List[np.ndarray] = []
        self._hardware_traces: List[np.ndarray] = []
        self._alignment_offset: int = 0
        self._resample_ratio: float = 1.0

    def load_emulated_traces(
        self,
        traces: Union[np.ndarray, List[np.ndarray], str]
    ) -> None:
        """Load emulated traces."""
        if isinstance(traces, str):
            data = np.load(traces)
            traces = data["traces"] if "traces" in data else data["arr_0"]

        if isinstance(traces, np.ndarray) and traces.ndim == 2:
            self._emulated_traces = [traces[i] for i in range(traces.shape[0])]
        else:
            self._emulated_traces = list(traces)

    def load_hardware_traces(
        self,
        traces: Union[np.ndarray, List[np.ndarray], str]
    ) -> None:
        """Load hardware traces."""
        if isinstance(traces, str):
            data = np.load(traces)
            traces = data["traces"] if "traces" in data else data["arr_0"]

        if isinstance(traces, np.ndarray) and traces.ndim == 2:
            self._hardware_traces = [traces[i] for i in range(traces.shape[0])]
        else:
            self._hardware_traces = list(traces)

    def auto_align(self, reference_idx: int = 0) -> int:
        """
        Automatically align traces using cross-correlation.

        Returns:
            Alignment offset in samples
        """
        if not self._emulated_traces or not self._hardware_traces:
            return 0

        emu = self._emulated_traces[reference_idx]
        hw = self._hardware_traces[reference_idx]

        # Resample if needed
        if len(emu) != len(hw):
            self._resample_ratio = len(hw) / len(emu)
            emu = np.interp(
                np.linspace(0, len(emu), len(hw)),
                np.arange(len(emu)),
                emu
            )

        # Cross-correlation
        correlation = np.correlate(hw - hw.mean(), emu - emu.mean(), mode='full')
        offset = np.argmax(correlation) - len(emu) + 1

        self._alignment_offset = offset
        return offset

    def calculate_correlation(
        self,
        align: bool = True,
        per_trace: bool = False
    ) -> Union[float, List[float]]:
        """
        Calculate correlation between emulated and hardware traces.

        Args:
            align: Auto-align traces first
            per_trace: Return correlation for each trace pair

        Returns:
            Correlation coefficient(s)
        """
        if not self._emulated_traces or not self._hardware_traces:
            return 0.0 if not per_trace else []

        if align:
            self.auto_align()

        correlations = []
        n_pairs = min(len(self._emulated_traces), len(self._hardware_traces))

        for i in range(n_pairs):
            emu = self._emulated_traces[i]
            hw = self._hardware_traces[i]

            # Resample emulated to match hardware
            if len(emu) != len(hw):
                emu = np.interp(
                    np.linspace(0, len(emu), len(hw)),
                    np.arange(len(emu)),
                    emu
                )

            # Apply alignment offset
            if self._alignment_offset > 0:
                hw = hw[self._alignment_offset:]
                emu = emu[:len(hw)]
            elif self._alignment_offset < 0:
                emu = emu[-self._alignment_offset:]
                hw = hw[:len(emu)]

            # Calculate Pearson correlation
            if len(emu) > 0 and len(hw) > 0:
                corr = np.corrcoef(emu, hw)[0, 1]
                correlations.append(corr if not np.isnan(corr) else 0.0)

        if per_trace:
            return correlations
        return float(np.mean(correlations)) if correlations else 0.0

    def calculate_mse(self, normalize: bool = True) -> float:
        """
        Calculate mean squared error between traces.

        Args:
            normalize: Normalize traces to [0, 1] first
        """
        if not self._emulated_traces or not self._hardware_traces:
            return float('inf')

        total_mse = 0.0
        n_pairs = min(len(self._emulated_traces), len(self._hardware_traces))

        for i in range(n_pairs):
            emu = self._emulated_traces[i].astype(np.float64)
            hw = self._hardware_traces[i].astype(np.float64)

            # Resample
            if len(emu) != len(hw):
                emu = np.interp(
                    np.linspace(0, len(emu), len(hw)),
                    np.arange(len(emu)),
                    emu
                )

            if normalize:
                emu = (emu - emu.min()) / (emu.max() - emu.min() + 1e-10)
                hw = (hw - hw.min()) / (hw.max() - hw.min() + 1e-10)

            total_mse += np.mean((emu - hw) ** 2)

        return total_mse / n_pairs

    def compare(self) -> ComparisonResult:
        """Run full comparison and return result."""
        self.auto_align()

        correlation = self.calculate_correlation(align=False)
        mse = self.calculate_mse()

        # Agreement score based on correlation
        agreement = max(0, correlation)  # Negative correlation = 0 agreement

        return ComparisonResult(
            metric=ComparisonMetric.CORRELATION,
            name="trace_comparison",
            description="Comparison of emulated vs hardware power traces",
            emulated_value=len(self._emulated_traces),
            hardware_value=len(self._hardware_traces),
            agreement=agreement,
            correlation=correlation,
            mse=mse,
            emulator_params={"alignment_offset": self._alignment_offset},
        )


class HardwareEmulatorBridge:
    """
    Bridge between Slab emulator and real hardware.

    Enables:
    - Running same attack on both emulator and hardware
    - Parameter transfer from successful emulated attacks
    - Validation of emulation model accuracy
    - Automated comparison studies
    """

    def __init__(
        self,
        hardware: Optional[HardwarePlatform] = None,
    ):
        self._hardware = hardware
        self._emulator = None  # Placeholder for slab emulator
        self._results: List[ComparisonResult] = []
        self._trace_comparator = TraceComparator()

    def set_hardware(self, hardware: HardwarePlatform) -> None:
        """Set hardware platform."""
        self._hardware = hardware

    def set_emulator(self, emulator: Any) -> None:
        """Set Slab emulator instance."""
        self._emulator = emulator

    def compare_glitch_campaign(
        self,
        emulator_results: List[Dict[str, Any]],
        hardware_results: List[Dict[str, Any]],
        tolerance_ns: float = 100.0
    ) -> ComparisonResult:
        """
        Compare glitch campaign results.

        Args:
            emulator_results: Results from slab_glitch campaign
            hardware_results: Results from hardware glitch campaign
            tolerance_ns: Timing tolerance for matching parameters

        Returns:
            ComparisonResult with agreement metrics
        """
        # Build lookup for emulator successes
        emu_successes = set()
        for r in emulator_results:
            if r.get("success", False):
                width = r.get("width_ns", r.get("width", 0))
                offset = r.get("offset_ns", r.get("offset", 0))
                emu_successes.add((round(width / tolerance_ns), round(offset / tolerance_ns)))

        # Check hardware successes against emulator
        matching = 0
        hw_successes = 0

        for r in hardware_results:
            if r.get("success", False):
                hw_successes += 1
                width = r.get("width_ns", r.get("width", 0))
                offset = r.get("offset_ns", r.get("offset", 0))
                key = (round(width / tolerance_ns), round(offset / tolerance_ns))
                if key in emu_successes:
                    matching += 1

        # Calculate agreement
        total_unique = len(emu_successes) + hw_successes - matching
        agreement = matching / total_unique if total_unique > 0 else 0.0

        result = ComparisonResult(
            metric=ComparisonMetric.SUCCESS_RATE,
            name="glitch_campaign_comparison",
            description="Comparison of glitch success regions",
            emulated_value=len(emu_successes),
            hardware_value=hw_successes,
            agreement=agreement,
            emulator_params={"total_attempts": len(emulator_results)},
            hardware_params={"total_attempts": len(hardware_results)},
            notes=f"Matching success points: {matching}",
        )

        self._results.append(result)
        return result

    def compare_traces(
        self,
        emulated_traces: Union[np.ndarray, str],
        hardware_traces: Union[np.ndarray, str],
    ) -> ComparisonResult:
        """
        Compare power traces from emulation and hardware.

        Args:
            emulated_traces: Traces from slab_sidechannels or file path
            hardware_traces: Traces from hardware capture or file path

        Returns:
            ComparisonResult with correlation metrics
        """
        self._trace_comparator.load_emulated_traces(emulated_traces)
        self._trace_comparator.load_hardware_traces(hardware_traces)

        result = self._trace_comparator.compare()
        self._results.append(result)
        return result

    def transfer_glitch_params(
        self,
        emulator_results: List[Dict[str, Any]],
        success_only: bool = True,
        scale_timing: float = 1.0
    ) -> List[Dict[str, Any]]:
        """
        Transfer glitch parameters from emulator to hardware format.

        Args:
            emulator_results: Results from slab_glitch
            success_only: Only transfer successful parameters
            scale_timing: Timing scale factor (e.g., for clock differences)

        Returns:
            Parameters in hardware format
        """
        params = []

        for r in emulator_results:
            if success_only and not r.get("success", False):
                continue

            hw_param = {
                "width_ns": r.get("width_ns", r.get("glitch_width", 0)) * scale_timing,
                "offset_ns": r.get("offset_ns", r.get("delay_cycles", 0)) * scale_timing,
                "repeat": r.get("repeat", 1),
                "original": r,  # Keep reference to original
            }
            params.append(hw_param)

        return params

    def run_validation_suite(
        self,
        test_cases: List[Dict[str, Any]],
        run_emulator: Callable[[Dict], Dict],
        run_hardware: Callable[[Dict], Dict],
        progress_callback: Optional[Callable[[int, int, ComparisonResult], None]] = None
    ) -> List[ComparisonResult]:
        """
        Run full validation suite comparing emulator and hardware.

        Args:
            test_cases: List of test configurations
            run_emulator: Function to run test on emulator
            run_hardware: Function to run test on hardware
            progress_callback: Called with (index, total, result)

        Returns:
            List of comparison results
        """
        results = []

        for i, test in enumerate(test_cases):
            # Run on emulator
            emu_result = run_emulator(test)

            # Run on hardware
            hw_result = run_hardware(test)

            # Compare
            comparison = ComparisonResult(
                metric=ComparisonMetric.SUCCESS_RATE,
                name=test.get("name", f"test_{i}"),
                description=test.get("description", ""),
                emulated_value=1 if emu_result.get("success") else 0,
                hardware_value=1 if hw_result.get("success") else 0,
                agreement=1.0 if emu_result.get("success") == hw_result.get("success") else 0.0,
                emulator_params=emu_result,
                hardware_params=hw_result,
            )

            results.append(comparison)
            self._results.append(comparison)

            if progress_callback:
                progress_callback(i, len(test_cases), comparison)

        return results

    def generate_report(self) -> Dict[str, Any]:
        """Generate summary report of all comparisons."""
        if not self._results:
            return {"error": "No comparison results available"}

        # Calculate overall agreement
        agreements = [r.agreement for r in self._results]
        avg_agreement = np.mean(agreements) if agreements else 0.0

        # Group by metric type
        by_metric: Dict[str, List[ComparisonResult]] = {}
        for r in self._results:
            key = r.metric.name
            if key not in by_metric:
                by_metric[key] = []
            by_metric[key].append(r)

        # Build report
        report = {
            "summary": {
                "total_comparisons": len(self._results),
                "average_agreement": float(avg_agreement),
                "pass_rate": sum(1 for r in self._results if r.is_acceptable()) / len(self._results),
            },
            "by_metric": {
                name: {
                    "count": len(results),
                    "avg_agreement": float(np.mean([r.agreement for r in results])),
                    "results": [r.to_dict() for r in results],
                }
                for name, results in by_metric.items()
            },
            "timestamp": datetime.now().isoformat(),
        }

        return report

    def save_report(self, path: str) -> None:
        """Save comparison report to JSON."""
        report = self.generate_report()
        with open(path, "w") as f:
            json.dump(report, f, indent=2)

    def describe_for_llm(self) -> str:
        """Get LLM-friendly description of comparison state."""
        lines = [
            "Hardware/Emulator Bridge Status",
            "=" * 35,
            "",
            f"Hardware connected: {self._hardware.connected if self._hardware else False}",
            f"Emulator configured: {self._emulator is not None}",
            f"Comparisons performed: {len(self._results)}",
            "",
        ]

        if self._results:
            agreements = [r.agreement for r in self._results]
            lines.extend([
                "Results Summary:",
                f"  Average agreement: {np.mean(agreements):.1%}",
                f"  Best agreement: {max(agreements):.1%}",
                f"  Worst agreement: {min(agreements):.1%}",
                "",
            ])

            # Recent results
            lines.append("Recent comparisons:")
            for r in self._results[-5:]:
                status = "✓" if r.is_acceptable() else "✗"
                lines.append(f"  {status} {r.name}: {r.agreement:.1%} agreement")

        return "\n".join(lines)
