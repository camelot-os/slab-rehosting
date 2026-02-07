"""
LaTeX Test Report Generator

Generates per-firmware test reports with TikZ architecture diagrams,
MMIO register access tables, initialization sequences, and test verdicts.
Pure-string LaTeX generation (no pylatex dependency).

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from slab_cortex_m.mmio_tracer import MMIOTrace, SpinLoopInfo


@dataclass
class TestBookReport:
    """All data needed to generate a test book for one firmware."""
    title: str
    mcu: str
    firmware_name: str
    peripherals: List[str] = field(default_factory=list)
    external_devices: List[str] = field(default_factory=list)
    build_command: str = ""
    run_command: str = ""
    mmio_count: int = 0
    device_transactions: int = 0
    uart_output: str = ""
    mmio_traces: List[MMIOTrace] = field(default_factory=list)
    spin_loops: List[SpinLoopInfo] = field(default_factory=list)
    duration: float = 0.0
    passed: bool = False
    timestamp: str = ""
    register_summary: List[Dict] = field(default_factory=list)
    peripheral_summary: Dict[str, Dict] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Color scheme (matching existing TikZ diagrams)
# ---------------------------------------------------------------------------

_LATEX_PREAMBLE = r"""\documentclass[a4paper,11pt]{article}
\usepackage[margin=2cm]{geometry}
\usepackage{tikz}
\usepackage{longtable}
\usepackage{booktabs}
\usepackage{fancyhdr}
\usepackage{xcolor}
\usepackage{listings}
\usepackage{hyperref}
\usepackage{fancyvrb}
\usetikzlibrary{arrows.meta,positioning,shapes.geometric,fit,backgrounds,calc}

\definecolor{securegreen}{RGB}{34,139,34}
\definecolor{nscyellow}{RGB}{255,193,7}
\definecolor{nsred}{RGB}{220,53,69}
\definecolor{trustzoneblue}{RGB}{0,123,255}
\definecolor{mcugray}{RGB}{100,100,100}
\definecolor{spiblue}{RGB}{0,102,204}
\definecolor{i2corange}{RGB}{230,126,34}
\definecolor{gpiored}{RGB}{192,57,43}
\definecolor{uartgreen}{RGB}{39,174,96}
\definecolor{passgreen}{RGB}{0,128,0}
\definecolor{failred}{RGB}{200,0,0}

\lstset{
  basicstyle=\ttfamily\small,
  breaklines=true,
  frame=single,
  backgroundcolor=\color{gray!10},
}

\pagestyle{fancy}
\fancyhf{}
\rhead{SLAB Emulation Test Report}
\lhead{\leftmark}
\rfoot{Page \thepage}
"""


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters in text strings."""
    text = text.replace('\\', '\\textbackslash ')
    text = text.replace('&', r'\&')
    text = text.replace('%', r'\%')
    text = text.replace('$', r'\$')
    text = text.replace('#', r'\#')
    text = text.replace('{', r'\{')
    text = text.replace('}', r'\}')
    text = text.replace('~', r'\textasciitilde ')
    text = text.replace('^', r'\textasciicircum ')
    # Underscore last -- after braces are handled
    text = text.replace('_', r'\_')
    return text


def _truncate(text: str, maxlen: int = 2000) -> str:
    """Truncate long text for LaTeX output."""
    if len(text) <= maxlen:
        return text
    return text[:maxlen] + "\n... (truncated)"


# ---------------------------------------------------------------------------
# TikZ Architecture Diagrams
# ---------------------------------------------------------------------------

def generate_architecture_tikz(report: TestBookReport) -> str:
    """Generate a TikZ block diagram showing MCU + peripherals + external devices."""
    # Classify peripherals by bus type
    bus_groups = {'AHB': [], 'APB1': [], 'APB2': [], 'Other': []}
    for pname in report.peripherals:
        upper = pname.upper()
        if any(k in upper for k in ('GPIO', 'DMA', 'RCC', 'CRC', 'FLASH')):
            bus_groups['AHB'].append(pname)
        elif any(k in upper for k in ('SPI', 'USART', 'UART', 'TIM')):
            bus_groups['APB2'].append(pname)
        elif any(k in upper for k in ('I2C', 'PWR', 'RTC', 'IWDG', 'WWDG')):
            bus_groups['APB1'].append(pname)
        else:
            bus_groups['Other'].append(pname)

    # Limit to 8 peripherals per group for readability
    for g in bus_groups:
        bus_groups[g] = bus_groups[g][:8]

    lines = []
    lines.append(r"\begin{tikzpicture}[")
    lines.append(r"    mcubox/.style={draw, thick, rounded corners=6pt, "
                 r"fill=mcugray!10, minimum width=6cm, minimum height=3cm},")
    lines.append(r"    periph/.style={draw, rounded corners=3pt, "
                 r"minimum width=2.2cm, minimum height=0.7cm, "
                 r"align=center, font=\small},")
    lines.append(r"    extdev/.style={draw, dashed, rounded corners=3pt, "
                 r"minimum width=2.2cm, minimum height=0.7cm, "
                 r"align=center, font=\small},")
    lines.append(r"    busline/.style={thick, -{Stealth[length=2mm]}},")
    lines.append(r"]")

    # MCU box
    lines.append(f"\\node[mcubox] (mcu) {{{_escape_latex(report.mcu)}}};")
    lines.append(f"\\node[above, font=\\bfseries] at (mcu.north) "
                 f"{{{_escape_latex(report.title)}}};")

    # Place peripherals around the MCU
    y_offset = 2.0
    for i, pname in enumerate(bus_groups['AHB'][:4]):
        color = _peripheral_color(pname)
        lines.append(
            f"\\node[periph, fill={color}!20, right=1.5cm] "
            f"at ([yshift={y_offset - i * 0.9}cm]mcu.east) "
            f"(p_{i}) {{{_escape_latex(pname)}}};")
        lines.append(f"\\draw[busline] (mcu.east) -- (p_{i}.west);")

    y_offset = 2.0
    for i, pname in enumerate(bus_groups['APB2'][:4]):
        color = _peripheral_color(pname)
        idx = i + 10
        lines.append(
            f"\\node[periph, fill={color}!20, left=1.5cm] "
            f"at ([yshift={y_offset - i * 0.9}cm]mcu.west) "
            f"(p_{idx}) {{{_escape_latex(pname)}}};")
        lines.append(f"\\draw[busline] (mcu.west) -- (p_{idx}.east);")

    # External devices below
    for i, dev in enumerate(report.external_devices[:4]):
        x_pos = -2.5 + i * 2.5
        lines.append(
            f"\\node[extdev, fill=nscyellow!20, below=2cm] "
            f"at ([xshift={x_pos}cm]mcu.south) "
            f"(ext_{i}) {{{_escape_latex(dev)}}};")
        lines.append(f"\\draw[busline, dashed] (mcu.south) -- (ext_{i}.north);")

    lines.append(r"\end{tikzpicture}")
    return '\n'.join(lines)


def _peripheral_color(name: str) -> str:
    """Map peripheral name to a TikZ color."""
    upper = name.upper()
    if 'SPI' in upper or 'QSPI' in upper:
        return 'spiblue'
    elif 'I2C' in upper or 'TWI' in upper:
        return 'i2corange'
    elif 'GPIO' in upper:
        return 'gpiored'
    elif 'USART' in upper or 'UART' in upper:
        return 'uartgreen'
    elif 'CRYP' in upper or 'HASH' in upper or 'RNG' in upper:
        return 'securegreen'
    else:
        return 'trustzoneblue'


# ---------------------------------------------------------------------------
# MMIO Timeline
# ---------------------------------------------------------------------------

def generate_mmio_timeline_tikz(traces: List[MMIOTrace],
                                 limit: int = 40) -> str:
    """Generate a TikZ timeline of the first N MMIO accesses."""
    subset = traces[:limit]
    if not subset:
        return "% No MMIO traces available"

    lines = []
    lines.append(r"\begin{tikzpicture}[")
    lines.append(r"    rbox/.style={draw, fill=trustzoneblue!15, "
                 r"minimum width=0.3cm, minimum height=0.25cm, "
                 r"font=\tiny, inner sep=1pt},")
    lines.append(r"    wbox/.style={draw, fill=nsred!15, "
                 r"minimum width=0.3cm, minimum height=0.25cm, "
                 r"font=\tiny, inner sep=1pt},")
    lines.append(r"]")

    # Compact table-like layout
    lines.append(r"\node[font=\tiny\bfseries] at (0, 0.3) {Seq};")
    lines.append(r"\node[font=\tiny\bfseries] at (0.8, 0.3) {R/W};")
    lines.append(r"\node[font=\tiny\bfseries] at (2.5, 0.3) {Peripheral};")
    lines.append(r"\node[font=\tiny\bfseries] at (4.5, 0.3) {Register};")
    lines.append(r"\node[font=\tiny\bfseries] at (6.5, 0.3) {Value};")

    for i, t in enumerate(subset):
        y = -i * 0.3
        rw = 'W' if t.is_write else 'R'
        style = 'wbox' if t.is_write else 'rbox'
        lines.append(
            f"\\node[font=\\tiny] at (0, {y}) {{{t.sequence}}};")
        lines.append(
            f"\\node[{style}] at (0.8, {y}) {{{rw}}};")
        lines.append(
            f"\\node[font=\\tiny] at (2.5, {y}) "
            f"{{{_escape_latex(t.peripheral_name)}}};")
        lines.append(
            f"\\node[font=\\tiny] at (4.5, {y}) "
            f"{{{_escape_latex(t.register_name)}}};")
        lines.append(
            f"\\node[font=\\tiny] at (6.5, {y}) "
            f"{{0x{t.value:08X}}};")

    lines.append(r"\end{tikzpicture}")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# LaTeX Tables
# ---------------------------------------------------------------------------

def generate_register_table(register_summary: List[Dict]) -> str:
    """Generate a LaTeX longtable of unique register accesses."""
    if not register_summary:
        return "No register accesses recorded."

    lines = []
    lines.append(r"\begin{longtable}{llrrr}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Peripheral} & \textbf{Register} & "
                 r"\textbf{Reads} & \textbf{Writes} & "
                 r"\textbf{Last Value} \\")
    lines.append(r"\midrule")
    lines.append(r"\endhead")

    for entry in register_summary:
        pname = _escape_latex(entry['peripheral'])
        rname = _escape_latex(entry['register'])
        lines.append(
            f"{pname} & {rname} & "
            f"{entry['reads']} & {entry['writes']} & "
            f"0x{entry['last_value']:08X} \\\\")

    lines.append(r"\bottomrule")
    lines.append(r"\end{longtable}")
    return '\n'.join(lines)


def generate_peripheral_summary_table(summary: Dict[str, Dict]) -> str:
    """Generate a summary table of per-peripheral access counts."""
    if not summary:
        return "No peripheral accesses recorded."

    lines = []
    lines.append(r"\begin{longtable}{lrrll}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Peripheral} & \textbf{Reads} & "
                 r"\textbf{Writes} & \textbf{Total} & "
                 r"\textbf{Top Register} \\")
    lines.append(r"\midrule")
    lines.append(r"\endhead")

    for pname, data in sorted(summary.items()):
        total = data['reads'] + data['writes']
        lines.append(
            f"{_escape_latex(pname)} & {data['reads']} & "
            f"{data['writes']} & {total} & "
            f"{_escape_latex(data.get('top_reg', ''))} \\\\")

    lines.append(r"\bottomrule")
    lines.append(r"\end{longtable}")
    return '\n'.join(lines)


def generate_init_sequence_table(traces: List[MMIOTrace],
                                  limit: int = 100) -> str:
    """Generate table of initialization register writes (for RE)."""
    writes = [t for t in traces if t.is_write][:limit]
    if not writes:
        return "No initialization writes detected."

    lines = []
    lines.append(r"\begin{longtable}{rllrl}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Seq} & \textbf{Peripheral} & "
                 r"\textbf{Register} & \textbf{Value} & "
                 r"\textbf{Bit-fields} \\")
    lines.append(r"\midrule")
    lines.append(r"\endhead")

    for t in writes:
        bf = _escape_latex(t.bitfields) if t.bitfields else ""
        lines.append(
            f"{t.sequence} & {_escape_latex(t.peripheral_name)} & "
            f"{_escape_latex(t.register_name)} & "
            f"0x{t.value:08X} & {bf} \\\\")

    lines.append(r"\bottomrule")
    lines.append(r"\end{longtable}")
    return '\n'.join(lines)


def generate_spin_loop_table(spin_loops: List[SpinLoopInfo]) -> str:
    """Generate table of detected spin loops."""
    if not spin_loops:
        return "No spin loops detected."

    lines = []
    lines.append(r"\begin{longtable}{llrlr}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Peripheral} & \textbf{Register} & "
                 r"\textbf{Count} & \textbf{Value} & "
                 r"\textbf{Seq Range} \\")
    lines.append(r"\midrule")
    lines.append(r"\endhead")

    for sl in spin_loops:
        lines.append(
            f"{_escape_latex(sl.peripheral)} & "
            f"{_escape_latex(sl.register)} & "
            f"{sl.count} & 0x{sl.value:08X} & "
            f"{sl.start_seq}--{sl.end_seq} \\\\")

    lines.append(r"\bottomrule")
    lines.append(r"\end{longtable}")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Full Test Book Generation
# ---------------------------------------------------------------------------

def generate_test_book(report: TestBookReport, output_dir: str) -> str:
    """Assemble a complete .tex test report document.

    Returns the path to the generated .tex file.
    """
    os.makedirs(output_dir, exist_ok=True)

    safe_name = report.firmware_name.replace('/', '_').replace(' ', '_')
    tex_path = os.path.join(output_dir, f"{safe_name}_report.tex")

    verdict_color = "passgreen" if report.passed else "failred"
    verdict_text = "PASS" if report.passed else "FAIL"

    sections = []

    # Preamble
    sections.append(_LATEX_PREAMBLE)
    sections.append(f"\\lfoot{{{_escape_latex(report.firmware_name)}}}")
    sections.append(r"\begin{document}")

    # Title page
    sections.append(r"\begin{center}")
    sections.append(r"{\LARGE\bfseries SLAB Emulation Test Report}\\[0.5cm]")
    sections.append(f"{{\\Large {_escape_latex(report.title)}}}\\\\[0.3cm]")
    sections.append(f"MCU: \\texttt{{{_escape_latex(report.mcu)}}} "
                    f"\\hspace{{1cm}} "
                    f"Firmware: \\texttt{{{_escape_latex(report.firmware_name)}}}")
    sections.append(f"\\\\[0.3cm]")
    sections.append(f"{{\\large\\color{{{verdict_color}}}\\textbf{{"
                    f"Verdict: {verdict_text}}}}}")
    sections.append(f"\\\\[0.2cm]")
    sections.append(f"Generated: {_escape_latex(report.timestamp)}")
    sections.append(r"\end{center}")
    sections.append(r"\vspace{1cm}")

    # Test summary box
    sections.append(r"\begin{center}")
    sections.append(r"\begin{tabular}{ll}")
    sections.append(r"\toprule")
    sections.append(f"MMIO Operations & {report.mmio_count} \\\\")
    sections.append(f"Device Transactions & {report.device_transactions} \\\\")
    sections.append(f"Duration & {report.duration:.2f}s \\\\")
    sections.append(f"Peripherals & {len(report.peripherals)} \\\\")
    sections.append(f"External Devices & {len(report.external_devices)} \\\\")
    sections.append(r"\bottomrule")
    sections.append(r"\end{tabular}")
    sections.append(r"\end{center}")

    # Section 1: Architecture diagram
    sections.append(r"\section{Architecture}")
    sections.append(generate_architecture_tikz(report))

    # Section 2: Peripheral inventory
    sections.append(r"\section{Peripheral Inventory}")
    sections.append(generate_peripheral_summary_table(report.peripheral_summary))

    # Section 3: Build and run commands
    sections.append(r"\section{Reproducibility}")
    sections.append(r"\subsection{Build Command}")
    if report.build_command:
        sections.append(r"\begin{lstlisting}")
        sections.append(report.build_command)
        sections.append(r"\end{lstlisting}")
    else:
        sections.append("Pre-built firmware (no build command recorded).")

    sections.append(r"\subsection{Run Command}")
    if report.run_command:
        sections.append(r"\begin{lstlisting}")
        sections.append(report.run_command)
        sections.append(r"\end{lstlisting}")

    # Section 4: MMIO timeline
    if report.mmio_traces:
        sections.append(r"\section{MMIO Access Timeline (first 40 accesses)}")
        sections.append(generate_mmio_timeline_tikz(report.mmio_traces, limit=40))

    # Section 5: Register access summary
    if report.register_summary:
        sections.append(r"\section{Register Access Summary}")
        sections.append(generate_register_table(report.register_summary))

    # Section 6: Initialization sequence (RE section)
    if report.mmio_traces:
        sections.append(r"\section{Initialization Sequence}")
        sections.append(
            r"Peripheral register writes during firmware startup "
            r"(useful for reverse engineering).")
        sections.append(generate_init_sequence_table(report.mmio_traces))

    # Section 7: Spin loop detection
    if report.spin_loops:
        sections.append(r"\section{Spin Loop Detection}")
        sections.append(
            r"Repeated register polling detected during execution. "
            r"These may indicate busy-wait loops on peripheral status registers.")
        sections.append(generate_spin_loop_table(report.spin_loops))

    # Section 8: UART output
    if report.uart_output:
        sections.append(r"\section{UART Console Output}")
        sections.append(r"\begin{Verbatim}[fontsize=\small]")
        sections.append(_truncate(report.uart_output))
        sections.append(r"\end{Verbatim}")

    # Section 9: Test verdict
    sections.append(r"\section{Test Verdict}")
    sections.append(r"\begin{center}")
    sections.append(f"{{\\Huge\\color{{{verdict_color}}}\\textbf{{"
                    f"{verdict_text}}}}}")
    sections.append(r"\end{center}")
    sections.append(r"\begin{itemize}")
    sections.append(f"\\item MMIO operations: {report.mmio_count}")
    sections.append(f"\\item Device transactions: {report.device_transactions}")
    sections.append(f"\\item Execution time: {report.duration:.2f}s")
    if report.spin_loops:
        sections.append(f"\\item Spin loops detected: {len(report.spin_loops)}")
    sections.append(r"\end{itemize}")

    sections.append(r"\end{document}")

    content = '\n\n'.join(sections)

    with open(tex_path, 'w') as f:
        f.write(content)

    return tex_path
