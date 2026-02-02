"""
Slab HW - Lascar Integration

Interface to Ledger's Lascar side-channel analysis framework.
Lascar provides:
- Efficient trace container management
- CPA/DPA attack engines
- Leakage models
- Trace processing pipelines

This module bridges Slab's trace acquisition with Lascar's analysis
capabilities, enabling seamless transition from hardware capture to attack.

Reference: https://github.com/Ledger-Donjon/lascar

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass, field
from typing import (
    Optional, Dict, Any, Callable, Iterator, List, Tuple,
    Union, TYPE_CHECKING
)
from pathlib import Path
import numpy as np
import logging

# Lazy import of lascar
try:
    import lascar
    from lascar import (
        TraceBatchContainer,
        AcquisitionSetup,
        Session,
        CpaEngine,
        DpaEngine,
        TTestEngine,
        SnrEngine,
        NicvEngine,
        PartitionerEngine,
        hamming_weight,
        sbox,
    )
    from lascar.tools.aes import Sbox as AesSbox
    HAS_LASCAR = True
except ImportError:
    HAS_LASCAR = False
    # Stub classes for type hints
    class TraceBatchContainer: pass
    class Session: pass
    class CpaEngine: pass
    class DpaEngine: pass

logger = logging.getLogger(__name__)


@dataclass
class LascarTraceSet:
    """
    Wrapper for trace data compatible with Lascar containers.

    Provides conversion between Slab's trace format and Lascar's
    TraceBatchContainer.
    """
    traces: np.ndarray           # Shape: (num_traces, num_samples)
    values: np.ndarray           # Shape: (num_traces, value_size)
    plaintext: Optional[np.ndarray] = None  # For crypto analysis
    ciphertext: Optional[np.ndarray] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str) -> "LascarTraceSet":
        """Load traces from file (NPZ format)."""
        data = np.load(path)
        return cls(
            traces=data["traces"],
            values=data.get("values", data.get("plaintext", np.array([]))),
            plaintext=data.get("plaintext"),
            ciphertext=data.get("ciphertext"),
            metadata=dict(data.get("metadata", {}).item()) if "metadata" in data else {},
        )

    def save(self, path: str) -> None:
        """Save traces to file (NPZ format)."""
        save_dict = {
            "traces": self.traces,
            "values": self.values,
            "metadata": np.array(self.metadata),
        }
        if self.plaintext is not None:
            save_dict["plaintext"] = self.plaintext
        if self.ciphertext is not None:
            save_dict["ciphertext"] = self.ciphertext
        np.savez_compressed(path, **save_dict)

    @property
    def num_traces(self) -> int:
        return self.traces.shape[0]

    @property
    def num_samples(self) -> int:
        return self.traces.shape[1]

    def to_lascar_container(self) -> "TraceBatchContainer":
        """Convert to Lascar TraceBatchContainer."""
        if not HAS_LASCAR:
            raise ImportError("Lascar not installed")

        return TraceBatchContainer(self.traces, self.values)

    def subset(self, indices: np.ndarray) -> "LascarTraceSet":
        """Create subset of traces."""
        return LascarTraceSet(
            traces=self.traces[indices],
            values=self.values[indices],
            plaintext=self.plaintext[indices] if self.plaintext is not None else None,
            ciphertext=self.ciphertext[indices] if self.ciphertext is not None else None,
            metadata=self.metadata.copy(),
        )

    def slice_samples(self, start: int, end: int) -> "LascarTraceSet":
        """Slice sample range."""
        return LascarTraceSet(
            traces=self.traces[:, start:end],
            values=self.values,
            plaintext=self.plaintext,
            ciphertext=self.ciphertext,
            metadata=self.metadata.copy(),
        )


class LascarSession:
    """
    Slab wrapper for Lascar analysis sessions.

    Simplifies setup of common side-channel attacks while maintaining
    full access to Lascar's capabilities.
    """

    def __init__(self, traceset: Optional[LascarTraceSet] = None):
        if not HAS_LASCAR:
            raise ImportError("Lascar not installed. Install with: pip install lascar")

        self._traceset = traceset
        self._container = None
        self._session = None
        self._engines: Dict[str, Any] = {}
        self._results: Dict[str, Any] = {}

        if traceset:
            self._container = traceset.to_lascar_container()

    def load_traces(self, path: str) -> None:
        """Load traces from file."""
        self._traceset = LascarTraceSet.from_file(path)
        self._container = self._traceset.to_lascar_container()

    def set_traces(self, traceset: LascarTraceSet) -> None:
        """Set trace data."""
        self._traceset = traceset
        self._container = traceset.to_lascar_container()

    def add_cpa_engine(
        self,
        name: str,
        byte_index: int,
        leakage_model: str = "hamming_weight",
        selection_function: Optional[Callable] = None,
    ) -> None:
        """
        Add CPA attack engine.

        Args:
            name: Engine identifier
            byte_index: Target key byte index
            leakage_model: "hamming_weight" or "identity"
            selection_function: Custom selection function (sbox output default)
        """
        if not HAS_LASCAR:
            raise ImportError("Lascar not installed")

        if selection_function is None:
            # Default: AES S-box output
            def selection_function(value, key_guess):
                return sbox[value[byte_index] ^ key_guess]

        if leakage_model == "hamming_weight":
            def leakage(x):
                return hamming_weight(x)
        else:
            def leakage(x):
                return x

        engine = CpaEngine(
            name=name,
            selection_function=selection_function,
            guess_range=range(256),
            leakage_model=leakage,
        )
        self._engines[name] = engine

    def add_dpa_engine(
        self,
        name: str,
        byte_index: int,
        bit_index: int = 0,
        selection_function: Optional[Callable] = None,
    ) -> None:
        """
        Add DPA attack engine.

        Args:
            name: Engine identifier
            byte_index: Target key byte index
            bit_index: Target bit within byte
            selection_function: Custom selection function
        """
        if not HAS_LASCAR:
            raise ImportError("Lascar not installed")

        if selection_function is None:
            def selection_function(value, key_guess):
                return (sbox[value[byte_index] ^ key_guess] >> bit_index) & 1

        engine = DpaEngine(
            name=name,
            selection_function=selection_function,
            guess_range=range(256),
        )
        self._engines[name] = engine

    def add_ttest_engine(self, name: str) -> None:
        """Add Welch's T-test engine for leakage detection."""
        if not HAS_LASCAR:
            raise ImportError("Lascar not installed")

        engine = TTestEngine(name=name)
        self._engines[name] = engine

    def add_snr_engine(self, name: str, partitioner: Callable) -> None:
        """Add SNR engine for signal-to-noise analysis."""
        if not HAS_LASCAR:
            raise ImportError("Lascar not installed")

        engine = SnrEngine(name=name, partitioner=partitioner)
        self._engines[name] = engine

    def run(
        self,
        batch_size: int = 1000,
        callback: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        Run all configured engines.

        Args:
            batch_size: Traces per batch
            callback: Progress callback (current, total)

        Returns:
            Dictionary of results by engine name
        """
        if not self._container:
            raise ValueError("No traces loaded")

        if not self._engines:
            raise ValueError("No engines configured")

        # Create session with all engines
        self._session = Session(
            self._container,
            engines=list(self._engines.values()),
        )

        # Run session
        total = self._traceset.num_traces if self._traceset else 0
        processed = 0

        self._session.run(batch_size=batch_size)

        # Collect results
        self._results = {}
        for name, engine in self._engines.items():
            self._results[name] = {
                "result": engine.finalize(),
                "name": name,
            }

        return self._results

    def get_best_key_guess(self, engine_name: str) -> Tuple[int, float]:
        """
        Get best key guess from CPA/DPA engine.

        Returns:
            (key_byte_value, correlation)
        """
        if engine_name not in self._results:
            raise ValueError(f"No results for engine {engine_name}")

        result = self._results[engine_name]["result"]
        # Result shape: (256, num_samples) for CPA
        max_corr = np.max(np.abs(result), axis=1)
        best_guess = np.argmax(max_corr)
        return int(best_guess), float(max_corr[best_guess])

    def get_all_key_bytes(self, prefix: str = "cpa_byte_") -> List[int]:
        """Get all recovered key bytes from multiple engines."""
        key = []
        for name in sorted(self._results.keys()):
            if name.startswith(prefix):
                guess, _ = self.get_best_key_guess(name)
                key.append(guess)
        return key

    def describe_results(self) -> str:
        """Get human-readable description of results."""
        if not self._results:
            return "No results available. Run analysis first."

        lines = ["Side-Channel Analysis Results", "=" * 30, ""]

        for name, data in self._results.items():
            result = data["result"]

            if "cpa" in name.lower():
                best, corr = self.get_best_key_guess(name)
                lines.append(f"{name}:")
                lines.append(f"  Best guess: 0x{best:02X} ({best})")
                lines.append(f"  Correlation: {corr:.4f}")
                lines.append("")
            elif "dpa" in name.lower():
                best, diff = self.get_best_key_guess(name)
                lines.append(f"{name}:")
                lines.append(f"  Best guess: 0x{best:02X} ({best})")
                lines.append(f"  Difference: {diff:.4f}")
                lines.append("")
            elif "ttest" in name.lower():
                max_t = np.max(np.abs(result))
                lines.append(f"{name}:")
                lines.append(f"  Max t-value: {max_t:.2f}")
                lines.append(f"  Leakage detected: {max_t > 4.5}")
                lines.append("")

        return "\n".join(lines)


class LascarEngine:
    """
    High-level Lascar analysis engine.

    Provides simplified interface for common attack scenarios.
    """

    def __init__(self):
        if not HAS_LASCAR:
            raise ImportError("Lascar not installed")

        self._traceset: Optional[LascarTraceSet] = None
        self._key_bytes: List[Optional[int]] = [None] * 16

    def load_traces(
        self,
        traces: np.ndarray,
        plaintexts: np.ndarray,
        ciphertexts: Optional[np.ndarray] = None
    ) -> None:
        """Load trace data."""
        self._traceset = LascarTraceSet(
            traces=traces,
            values=plaintexts,
            plaintext=plaintexts,
            ciphertext=ciphertexts,
        )

    def attack_aes_key(
        self,
        byte_indices: Optional[List[int]] = None,
        method: str = "cpa",
        progress_callback: Optional[Callable[[int, int, int, float], None]] = None
    ) -> Tuple[List[int], Dict[str, float]]:
        """
        Attack AES key using CPA/DPA.

        Args:
            byte_indices: Key bytes to attack (default: all 16)
            method: "cpa" or "dpa"
            progress_callback: Called with (byte_idx, best_guess, correlation)

        Returns:
            (recovered_key, correlations_per_byte)
        """
        if not self._traceset:
            raise ValueError("No traces loaded")

        if byte_indices is None:
            byte_indices = list(range(16))

        correlations = {}

        for byte_idx in byte_indices:
            session = LascarSession(self._traceset)

            if method == "cpa":
                session.add_cpa_engine(f"cpa_{byte_idx}", byte_idx)
            else:
                session.add_dpa_engine(f"dpa_{byte_idx}", byte_idx)

            session.run()
            guess, corr = session.get_best_key_guess(f"{method}_{byte_idx}")

            self._key_bytes[byte_idx] = guess
            correlations[f"byte_{byte_idx}"] = corr

            if progress_callback:
                progress_callback(byte_idx, guess, len(byte_indices), corr)

        # Return only recovered bytes
        key = [b if b is not None else 0 for b in self._key_bytes]
        return key[:max(byte_indices) + 1], correlations

    def detect_leakage(self, group_function: Callable) -> Tuple[bool, float]:
        """
        Detect leakage using Welch's T-test.

        Args:
            group_function: Function to partition traces into groups

        Returns:
            (leakage_detected, max_t_value)
        """
        if not self._traceset:
            raise ValueError("No traces loaded")

        session = LascarSession(self._traceset)
        session.add_ttest_engine("ttest")
        session.run()

        result = session._results["ttest"]["result"]
        max_t = np.max(np.abs(result))

        return max_t > 4.5, float(max_t)

    def describe_for_llm(self) -> str:
        """Get LLM-friendly description of analysis state."""
        lines = [
            "Lascar Analysis Engine State",
            "",
        ]

        if self._traceset:
            lines.extend([
                f"Traces loaded: {self._traceset.num_traces}",
                f"Samples per trace: {self._traceset.num_samples}",
                "",
            ])

        recovered = [(i, b) for i, b in enumerate(self._key_bytes) if b is not None]
        if recovered:
            lines.append("Recovered key bytes:")
            for idx, val in recovered:
                lines.append(f"  Byte {idx}: 0x{val:02X}")

            # Show full key if all bytes recovered
            if len(recovered) == 16:
                key_hex = "".join(f"{b:02X}" for b in self._key_bytes)
                lines.extend(["", f"Full key: {key_hex}"])

        return "\n".join(lines)


# Convenience functions
def create_lascar_session(
    traces: Optional[np.ndarray] = None,
    values: Optional[np.ndarray] = None,
    path: Optional[str] = None
) -> LascarSession:
    """
    Create Lascar analysis session.

    Args:
        traces: Trace array (num_traces, num_samples)
        values: Value array (num_traces, value_size)
        path: Path to trace file (alternative to arrays)

    Returns:
        Configured LascarSession
    """
    if path:
        traceset = LascarTraceSet.from_file(path)
    elif traces is not None and values is not None:
        traceset = LascarTraceSet(traces=traces, values=values)
    else:
        traceset = None

    return LascarSession(traceset)


class LascarCPA(LascarEngine):
    """Convenience class for CPA attacks."""

    def attack(
        self,
        byte_indices: Optional[List[int]] = None,
        progress_callback: Optional[Callable] = None
    ) -> Tuple[List[int], Dict[str, float]]:
        """Run CPA attack."""
        return self.attack_aes_key(byte_indices, "cpa", progress_callback)


class LascarDPA(LascarEngine):
    """Convenience class for DPA attacks."""

    def attack(
        self,
        byte_indices: Optional[List[int]] = None,
        progress_callback: Optional[Callable] = None
    ) -> Tuple[List[int], Dict[str, float]]:
        """Run DPA attack."""
        return self.attack_aes_key(byte_indices, "dpa", progress_callback)
