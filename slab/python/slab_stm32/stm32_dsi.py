"""
STM32 DSI Host Controller Emulation

Implements the MIPI DSI Host peripheral found in STM32 MCUs with
display interfaces (F4x9, H7, U5A9/U5G9).

Features:
- Video mode and Command mode
- D-PHY PLL and regulator status
- Generic Short/Long packet interface (GHCR/GPDR)
- Wrapper registers for STM32-specific integration
- FIFO status in GPSR

Reference: RM0456 (STM32U5) DSI chapter.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable

from .stm32_base import STM32Peripheral, STATUS_OK


class STM32DSI(STM32Peripheral):
    """
    STM32 MIPI DSI Host controller.

    Register map (RM0456):
        Core:
        0x00: VR       Version
        0x04: CR       Control
        0x08: CCR      Clock Control
        0x0C: LVCIDR   LTDC VCID
        0x10: LCOLCR   LTDC Color Coding
        0x14: LPCR     LTDC Polarity Configuration
        0x18: LPMCR    LTDC LP Mode Configuration

        Flow Control:
        0x2C: PCR      Protocol Configuration
        0x34: MCR      Mode Configuration
        0x38: VMCR     Video Mode Configuration
        0x3C: VPCR     Video Packet Configuration
        0x40: VCCR     Video Chunks Configuration
        0x44: VNPCR    Video Null Packet Configuration
        0x48: VHSACR   Video HSA Configuration
        0x4C: VHBPCR   Video HBP Configuration
        0x50: VLCR     Video Line Configuration
        0x54: VVSACR   Video VSA Configuration
        0x58: VVBPCR   Video VBP Configuration
        0x5C: VVFPCR   Video VFP Configuration
        0x60: VVACR    Video VA Configuration

        Command Mode:
        0x64: LCCR     Command Configuration
        0x68: CMCR     Command Mode Configuration
        0x6C: GHCR     Generic Header Configuration
        0x70: GPDR     Generic Payload Data
        0x74: GPSR     Generic Packet Status
        0x78: TCCR0    Timeout Counter Configuration 0
        0x7C: TCCR1    Timeout Counter Configuration 1
        0x80: TCCR2    Timeout Counter Configuration 2
        0x84: TCCR3    Timeout Counter Configuration 3
        0x88: TCCR4    Timeout Counter Configuration 4
        0x8C: TCCR5    Timeout Counter Configuration 5

        PHY:
        0xA0: PCTLR    PHY Control
        0xA4: PCONFR   PHY Configuration
        0xA8: PUCR     PHY ULPS Control
        0xB0: PSR      PHY Status

        Interrupts:
        0xBC: ISR0     Interrupt Status 0
        0xC0: ISR1     Interrupt Status 1
        0xC4: IER0     Interrupt Enable 0
        0xC8: IER1     Interrupt Enable 1

        Wrapper:
        0x400: WCFGR   Wrapper Configuration
        0x404: WCR     Wrapper Control
        0x408: WIER    Wrapper Interrupt Enable
        0x40C: WISR    Wrapper Interrupt Status
        0x410: WIFCR   Wrapper Interrupt Flag Clear
        0x430: WRPCR   Wrapper Regulator and PLL Control
    """

    # Core registers
    VR      = 0x00
    CR      = 0x04
    CCR     = 0x08
    LVCIDR  = 0x0C
    LCOLCR  = 0x10
    LPCR    = 0x14
    LPMCR   = 0x18

    # Flow control
    PCR     = 0x2C
    MCR     = 0x34
    VMCR    = 0x38
    VPCR    = 0x3C
    VCCR    = 0x40
    VNPCR   = 0x44
    VHSACR  = 0x48
    VHBPCR  = 0x4C
    VLCR    = 0x50
    VVSACR  = 0x54
    VVBPCR  = 0x58
    VVFPCR  = 0x5C
    VVACR   = 0x60

    # Command mode
    LCCR    = 0x64
    CMCR    = 0x68
    GHCR    = 0x6C
    GPDR    = 0x70
    GPSR    = 0x74
    TCCR0   = 0x78
    TCCR1   = 0x7C
    TCCR2   = 0x80
    TCCR3   = 0x84
    TCCR4   = 0x88
    TCCR5   = 0x8C

    # PHY registers
    PCTLR   = 0xA0
    PCONFR  = 0xA4
    PUCR    = 0xA8
    PSR     = 0xB0

    # Interrupt registers
    ISR0    = 0xBC
    ISR1    = 0xC0
    IER0    = 0xC4
    IER1    = 0xC8

    # Wrapper registers
    WCFGR   = 0x400
    WCR     = 0x404
    WIER    = 0x408
    WISR    = 0x40C
    WIFCR   = 0x410
    WRPCR   = 0x430

    # Version constant (DSI Host v1.31.0)
    DSI_VERSION = 0x3133302A

    # CR bits
    CR_EN = 1 << 0

    # GPSR bits (Generic Packet Status)
    GPSR_CMDFE  = 1 << 0  # Command FIFO Empty
    GPSR_CMDFF  = 1 << 1  # Command FIFO Full
    GPSR_PWRFE  = 1 << 2  # Payload Write FIFO Empty
    GPSR_PWRFF  = 1 << 3  # Payload Write FIFO Full
    GPSR_PRDFE  = 1 << 4  # Payload Read FIFO Empty
    GPSR_PRDFF  = 1 << 5  # Payload Read FIFO Full
    GPSR_RCB    = 1 << 6  # Read Command Busy

    # WISR bits (Wrapper Interrupt Status)
    WISR_TEIF   = 1 << 0   # Tearing Effect Interrupt Flag
    WISR_ERIF   = 1 << 1   # End of Refresh Interrupt Flag
    WISR_BUSY   = 1 << 2   # Busy Flag
    WISR_PLLLS  = 1 << 8   # PLL Lock Status
    WISR_PLLLIF = 1 << 9   # PLL Lock Interrupt Flag
    WISR_PLLUIF = 1 << 10  # PLL Unlock Interrupt Flag
    WISR_RRS    = 1 << 12  # Regulator Ready Status
    WISR_RRIF   = 1 << 13  # Regulator Ready Interrupt Flag

    # WRPCR bits
    WRPCR_PLLEN = 1 << 0   # PLL Enable
    WRPCR_NDIV  = 0x7F << 2  # PLL N divider
    WRPCR_IDF   = 0xF << 11  # PLL input divider
    WRPCR_ODF   = 0x3 << 16  # PLL output divider
    WRPCR_REGEN = 1 << 24  # Regulator Enable

    # PSR bits (PHY Status)
    PSR_PD    = 1 << 1   # PHY Direction
    PSR_PSSC  = 1 << 2   # PHY Stop State Clock
    PSR_UANC  = 1 << 3   # ULPS Active Not Clock
    PSR_PSS0  = 1 << 4   # PHY Stop State Lane 0
    PSR_UAN0  = 1 << 5   # ULPS Active Not Lane 0
    PSR_RUE0  = 1 << 6   # RX ULPS Escape Lane 0
    PSR_PSS1  = 1 << 7   # PHY Stop State Lane 1
    PSR_UAN1  = 1 << 8   # ULPS Active Not Lane 1

    def __init__(self, base: int = 0x40016C00, irq: int = 137):
        super().__init__("DSI", base, 0x500, irq)

        # Core registers
        self.cr = 0
        self.ccr = 0
        self.lvcidr = 0
        self.lcolcr = 0
        self.lpcr = 0
        self.lpmcr = 0

        # Video mode
        self.pcr = 0
        self.mcr = 1   # Command mode by default
        self.vmcr = 0
        self.vpcr = 0
        self.vccr = 0
        self.vnpcr = 0
        self.vhsacr = 0
        self.vhbpcr = 0
        self.vlcr = 0
        self.vvsacr = 0
        self.vvbpcr = 0
        self.vvfpcr = 0
        self.vvacr = 0

        # Command mode
        self.lccr = 0
        self.cmcr = 0
        self.tccr = [0] * 6

        # PHY
        self.pctlr = 0
        self.pconfr = 0x01  # 1 data lane default
        self.pucr = 0

        # Interrupts
        self.isr0 = 0
        self.isr1 = 0
        self.ier0 = 0
        self.ier1 = 0

        # Wrapper
        self.wcfgr = 0
        self.wcr = 0
        self.wier = 0
        self.wisr = 0
        self.wrpcr = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.VR:
            return self.DSI_VERSION
        elif offset == self.CR:
            return self.cr
        elif offset == self.CCR:
            return self.ccr
        elif offset == self.LVCIDR:
            return self.lvcidr
        elif offset == self.LCOLCR:
            return self.lcolcr
        elif offset == self.LPCR:
            return self.lpcr
        elif offset == self.LPMCR:
            return self.lpmcr
        elif offset == self.PCR:
            return self.pcr
        elif offset == self.MCR:
            return self.mcr
        elif offset == self.VMCR:
            return self.vmcr
        elif offset == self.VPCR:
            return self.vpcr
        elif offset == self.VCCR:
            return self.vccr
        elif offset == self.VNPCR:
            return self.vnpcr
        elif offset == self.VHSACR:
            return self.vhsacr
        elif offset == self.VHBPCR:
            return self.vhbpcr
        elif offset == self.VLCR:
            return self.vlcr
        elif offset == self.VVSACR:
            return self.vvsacr
        elif offset == self.VVBPCR:
            return self.vvbpcr
        elif offset == self.VVFPCR:
            return self.vvfpcr
        elif offset == self.VVACR:
            return self.vvacr
        elif offset == self.LCCR:
            return self.lccr
        elif offset == self.CMCR:
            return self.cmcr
        elif offset == self.GHCR:
            return 0  # Write-only
        elif offset == self.GPDR:
            return 0  # Read data would come from display panel
        elif offset == self.GPSR:
            return self._compute_gpsr()
        elif self.TCCR0 <= offset <= self.TCCR5:
            idx = (offset - self.TCCR0) // 4
            return self.tccr[idx]
        elif offset == self.PCTLR:
            return self.pctlr
        elif offset == self.PCONFR:
            return self.pconfr
        elif offset == self.PUCR:
            return self.pucr
        elif offset == self.PSR:
            return self._compute_psr()
        elif offset == self.ISR0:
            return self.isr0
        elif offset == self.ISR1:
            return self.isr1
        elif offset == self.IER0:
            return self.ier0
        elif offset == self.IER1:
            return self.ier1
        elif offset == self.WCFGR:
            return self.wcfgr
        elif offset == self.WCR:
            return self.wcr
        elif offset == self.WIER:
            return self.wier
        elif offset == self.WISR:
            return self._compute_wisr()
        elif offset == self.WIFCR:
            return 0  # Write-only
        elif offset == self.WRPCR:
            return self.wrpcr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self.cr = value
        elif offset == self.CCR:
            self.ccr = value
        elif offset == self.LVCIDR:
            self.lvcidr = value & 0x3
        elif offset == self.LCOLCR:
            self.lcolcr = value
        elif offset == self.LPCR:
            self.lpcr = value
        elif offset == self.LPMCR:
            self.lpmcr = value
        elif offset == self.PCR:
            self.pcr = value
        elif offset == self.MCR:
            self.mcr = value
        elif offset == self.VMCR:
            self.vmcr = value
        elif offset == self.VPCR:
            self.vpcr = value
        elif offset == self.VCCR:
            self.vccr = value
        elif offset == self.VNPCR:
            self.vnpcr = value
        elif offset == self.VHSACR:
            self.vhsacr = value
        elif offset == self.VHBPCR:
            self.vhbpcr = value
        elif offset == self.VLCR:
            self.vlcr = value
        elif offset == self.VVSACR:
            self.vvsacr = value
        elif offset == self.VVBPCR:
            self.vvbpcr = value
        elif offset == self.VVFPCR:
            self.vvfpcr = value
        elif offset == self.VVACR:
            self.vvacr = value
        elif offset == self.LCCR:
            self.lccr = value
        elif offset == self.CMCR:
            self.cmcr = value
        elif offset == self.GHCR:
            self._process_generic_command(value)
        elif offset == self.GPDR:
            pass  # Payload data write (buffered)
        elif self.TCCR0 <= offset <= self.TCCR5:
            idx = (offset - self.TCCR0) // 4
            self.tccr[idx] = value
        elif offset == self.PCTLR:
            self.pctlr = value
        elif offset == self.PCONFR:
            self.pconfr = value
        elif offset == self.PUCR:
            self.pucr = value
        elif offset == self.IER0:
            self.ier0 = value
        elif offset == self.IER1:
            self.ier1 = value
        elif offset == self.WCFGR:
            self.wcfgr = value
        elif offset == self.WCR:
            self.wcr = value
        elif offset == self.WIER:
            self.wier = value
        elif offset == self.WIFCR:
            # Clear wrapper interrupt flags
            self.wisr &= ~value
        elif offset == self.WRPCR:
            self.wrpcr = value

    def _compute_gpsr(self) -> int:
        """Compute Generic Packet Status Register.

        Shows FIFOs as empty/not-full to indicate readiness.
        """
        # Command FIFO empty, not full; Payload write FIFO empty, not full;
        # Payload read FIFO empty; no read command busy
        return (self.GPSR_CMDFE | self.GPSR_PWRFE | self.GPSR_PRDFE)

    def _compute_psr(self) -> int:
        """Compute PHY Status Register.

        When PHY is enabled, report lanes in stop state (ready).
        """
        if self.pctlr & 0x3:  # DEN or CKE enabled
            # Clock and data lanes in stop state
            return self.PSR_PSSC | self.PSR_PSS0 | self.PSR_UAN0 | self.PSR_UANC
        return 0

    def _compute_wisr(self) -> int:
        """Compute Wrapper Interrupt Status Register.

        PLL lock and regulator ready are hardware status bits.
        """
        wisr = self.wisr

        # PLL lock status: locked when PLL enabled
        if self.wrpcr & self.WRPCR_PLLEN:
            wisr |= self.WISR_PLLLS

        # Regulator ready: ready when regulator enabled
        if self.wrpcr & self.WRPCR_REGEN:
            wisr |= self.WISR_RRS

        return wisr

    def _process_generic_command(self, ghcr: int):
        """Process a generic DSI command via GHCR register."""
        dt = ghcr & 0x3F        # Data type
        vc = (ghcr >> 6) & 0x3  # Virtual channel
        data = (ghcr >> 8)      # Data (short packet payload or word count)
        self.log.debug(f"DSI generic command: DT=0x{dt:02X} VC={vc} DATA=0x{data:04X}")

    def _update_irq(self):
        """Assert/deassert IRQ based on interrupt status/enable."""
        pending = bool(
            (self.isr0 & self.ier0) |
            (self.isr1 & self.ier1)
        )
        if self.irq_callback:
            self.irq_callback(self.irq, 1 if pending else 0)
