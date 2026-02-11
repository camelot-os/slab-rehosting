"""
Tests for STM32 LTDC and DSI Host peripherals and U5A9 peripheral set.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from slab_stm32.stm32_ltdc import STM32LTDC
from slab_stm32.stm32_dsi import STM32DSI
from slab_stm32.stm32u5xx import STM32U5A9PeripheralSet, STM32U5A5PeripheralSet


# ---------------------------------------------------------------------------
# LTDC tests
# ---------------------------------------------------------------------------

class TestLTDC:
    """Test LTDC register access and layer configuration."""

    def setup_method(self):
        self.ltdc = STM32LTDC(base=0x40016800, irq=135)
        self.base = 0x40016800

    def test_reset_values(self):
        assert self.ltdc.read(self.base + 0x08, 4)[0] == 0  # SSCR
        assert self.ltdc.read(self.base + 0x18, 4)[0] == 0  # GCR
        assert self.ltdc.read(self.base + 0x34, 4)[0] == 0  # IER

    def test_gcr_enable(self):
        self.ltdc.write(self.base + 0x18, 4, STM32LTDC.GCR_LTDCEN)
        assert self.ltdc.is_enabled()
        self.ltdc.write(self.base + 0x18, 4, 0)
        assert not self.ltdc.is_enabled()

    def test_bccr(self):
        self.ltdc.write(self.base + 0x2C, 4, 0x00FF0000)  # Red background
        assert self.ltdc.read(self.base + 0x2C, 4)[0] == 0x00FF0000

    def test_timing_registers(self):
        self.ltdc.write(self.base + 0x08, 4, 0x000300C7)  # SSCR
        self.ltdc.write(self.base + 0x0C, 4, 0x0029014F)  # BPCR
        self.ltdc.write(self.base + 0x10, 4, 0x0109024F)  # AWCR
        self.ltdc.write(self.base + 0x14, 4, 0x010D0257)  # TWCR
        assert self.ltdc.read(self.base + 0x08, 4)[0] == 0x000300C7
        assert self.ltdc.read(self.base + 0x0C, 4)[0] == 0x0029014F

    def test_layer1_config(self):
        # L1CR: enable
        self.ltdc.write(self.base + 0x84, 4, 0x01)
        assert self.ltdc.read(self.base + 0x84, 4)[0] == 0x01

        # L1WHPCR: window horizontal
        self.ltdc.write(self.base + 0x88, 4, 0x024F002A)
        assert self.ltdc.read(self.base + 0x88, 4)[0] == 0x024F002A

        # L1WVPCR: window vertical
        self.ltdc.write(self.base + 0x8C, 4, 0x0109000A)
        assert self.ltdc.read(self.base + 0x8C, 4)[0] == 0x0109000A

        # L1PFCR: RGB565
        self.ltdc.write(self.base + 0x94, 4, STM32LTDC.PF_RGB565)
        assert self.ltdc.read(self.base + 0x94, 4)[0] == STM32LTDC.PF_RGB565

        # L1CACR: constant alpha
        self.ltdc.write(self.base + 0x98, 4, 0x80)
        assert self.ltdc.read(self.base + 0x98, 4)[0] == 0x80

        # L1CFBAR: framebuffer address
        self.ltdc.write(self.base + 0xA8, 4, 0x20000000)
        assert self.ltdc.read(self.base + 0xA8, 4)[0] == 0x20000000

        # L1CFBLR: framebuffer length
        self.ltdc.write(self.base + 0xAC, 4, 0x01E00003)
        assert self.ltdc.read(self.base + 0xAC, 4)[0] == 0x01E00003

        # L1CFBLNR: framebuffer lines
        self.ltdc.write(self.base + 0xB0, 4, 240)
        assert self.ltdc.read(self.base + 0xB0, 4)[0] == 240

    def test_layer2_config(self):
        # L2CR: enable
        self.ltdc.write(self.base + 0x104, 4, 0x01)
        assert self.ltdc.read(self.base + 0x104, 4)[0] == 0x01

        # L2PFCR
        self.ltdc.write(self.base + 0x114, 4, STM32LTDC.PF_ARGB8888)
        assert self.ltdc.read(self.base + 0x114, 4)[0] == STM32LTDC.PF_ARGB8888

    def test_srcr_reload(self):
        reload_called = [False]
        self.ltdc.on_reload = lambda: reload_called.__setitem__(0, True)

        self.ltdc.write(self.base + 0x24, 4, STM32LTDC.SRCR_IMR)
        assert reload_called[0]

        # ISR should have RRIF set
        isr = self.ltdc.read(self.base + 0x38, 4)[0]
        assert isr & STM32LTDC.INT_RRIF

    def test_icr_clears_isr(self):
        self.ltdc.isr = STM32LTDC.INT_RRIF | STM32LTDC.INT_LIF
        self.ltdc.write(self.base + 0x3C, 4, STM32LTDC.INT_LIF)  # ICR
        assert self.ltdc.isr == STM32LTDC.INT_RRIF

    def test_irq_fires(self):
        irq_fired = [False]
        self.ltdc.irq_callback = lambda irq, level: irq_fired.__setitem__(0, bool(level))

        # Enable RRIF interrupt
        self.ltdc.write(self.base + 0x34, 4, STM32LTDC.INT_RRIF)

        # Trigger reload
        self.ltdc.write(self.base + 0x24, 4, STM32LTDC.SRCR_VBR)
        assert irq_fired[0]

    def test_get_layer_info(self):
        self.ltdc.write(self.base + 0x84, 4, 0x01)  # Enable
        self.ltdc.write(self.base + 0x94, 4, STM32LTDC.PF_RGB565)
        self.ltdc.write(self.base + 0xA8, 4, 0x20010000)

        info = self.ltdc.get_layer_info(0)
        assert info['enabled']
        assert info['pixel_format'] == STM32LTDC.PF_RGB565
        assert info['fb_address'] == 0x20010000

    def test_cdsr(self):
        """CDSR should return non-zero status."""
        cdsr = self.ltdc.read(self.base + 0x48, 4)[0]
        assert cdsr & 0x01  # VSYNCS

    def test_lipcr(self):
        self.ltdc.write(self.base + 0x40, 4, 200)
        assert self.ltdc.read(self.base + 0x40, 4)[0] == 200


# ---------------------------------------------------------------------------
# DSI tests
# ---------------------------------------------------------------------------

class TestDSI:
    """Test DSI Host register access and status."""

    def setup_method(self):
        self.dsi = STM32DSI(base=0x40016C00, irq=137)
        self.base = 0x40016C00

    def test_version_register(self):
        vr = self.dsi.read(self.base + 0x00, 4)[0]
        assert vr == STM32DSI.DSI_VERSION

    def test_cr_enable(self):
        self.dsi.write(self.base + 0x04, 4, STM32DSI.CR_EN)
        assert self.dsi.read(self.base + 0x04, 4)[0] & STM32DSI.CR_EN

    def test_lvcidr(self):
        self.dsi.write(self.base + 0x0C, 4, 0x02)  # VCID=2
        assert self.dsi.read(self.base + 0x0C, 4)[0] == 0x02

    def test_lcolcr(self):
        self.dsi.write(self.base + 0x10, 4, 0x05)  # 24-bit RGB888
        assert self.dsi.read(self.base + 0x10, 4)[0] == 0x05

    def test_pconfr_default(self):
        """Default: 1 data lane."""
        assert self.dsi.read(self.base + 0xA4, 4)[0] == 0x01

    def test_pconfr_two_lanes(self):
        self.dsi.write(self.base + 0xA4, 4, 0x02)  # 2 data lanes
        assert self.dsi.read(self.base + 0xA4, 4)[0] == 0x02

    def test_phy_status_inactive(self):
        """PSR should be 0 when PHY is disabled."""
        psr = self.dsi.read(self.base + 0xB0, 4)[0]
        assert psr == 0

    def test_phy_status_active(self):
        """PSR should show lanes in stop state when PHY enabled."""
        self.dsi.write(self.base + 0xA0, 4, 0x03)  # DEN + CKE
        psr = self.dsi.read(self.base + 0xB0, 4)[0]
        assert psr & STM32DSI.PSR_PSSC  # Clock lane stop
        assert psr & STM32DSI.PSR_PSS0  # Data lane 0 stop

    def test_gpsr_fifo_status(self):
        """GPSR should show FIFOs empty and ready."""
        gpsr = self.dsi.read(self.base + 0x74, 4)[0]
        assert gpsr & STM32DSI.GPSR_CMDFE   # Command FIFO empty
        assert gpsr & STM32DSI.GPSR_PWRFE   # Write FIFO empty
        assert not (gpsr & STM32DSI.GPSR_CMDFF)  # Not full

    def test_wisr_pll_lock(self):
        """WISR should show PLL locked when WRPCR.PLLEN is set."""
        # PLL not enabled
        wisr = self.dsi.read(self.base + 0x40C, 4)[0]
        assert not (wisr & STM32DSI.WISR_PLLLS)

        # Enable PLL
        self.dsi.write(self.base + 0x430, 4, STM32DSI.WRPCR_PLLEN)
        wisr = self.dsi.read(self.base + 0x40C, 4)[0]
        assert wisr & STM32DSI.WISR_PLLLS

    def test_wisr_regulator_ready(self):
        """WISR should show regulator ready when WRPCR.REGEN is set."""
        self.dsi.write(self.base + 0x430, 4, STM32DSI.WRPCR_REGEN)
        wisr = self.dsi.read(self.base + 0x40C, 4)[0]
        assert wisr & STM32DSI.WISR_RRS

    def test_wisr_pll_and_regulator(self):
        """Both PLL lock and regulator ready should be set."""
        self.dsi.write(self.base + 0x430, 4,
                       STM32DSI.WRPCR_PLLEN | STM32DSI.WRPCR_REGEN)
        wisr = self.dsi.read(self.base + 0x40C, 4)[0]
        assert wisr & STM32DSI.WISR_PLLLS
        assert wisr & STM32DSI.WISR_RRS

    def test_wifcr_clears_wisr(self):
        """WIFCR should clear WISR flags."""
        self.dsi.wisr = STM32DSI.WISR_TEIF | STM32DSI.WISR_ERIF
        self.dsi.write(self.base + 0x410, 4, STM32DSI.WISR_TEIF)
        assert not (self.dsi.wisr & STM32DSI.WISR_TEIF)
        assert self.dsi.wisr & STM32DSI.WISR_ERIF

    def test_video_mode_config(self):
        self.dsi.write(self.base + 0x38, 4, 0x01)  # VMCR
        self.dsi.write(self.base + 0x3C, 4, 480)    # VPCR (packet size)
        self.dsi.write(self.base + 0x48, 4, 10)     # VHSACR
        self.dsi.write(self.base + 0x4C, 4, 20)     # VHBPCR
        self.dsi.write(self.base + 0x50, 4, 480)    # VLCR

        assert self.dsi.read(self.base + 0x38, 4)[0] == 0x01
        assert self.dsi.read(self.base + 0x3C, 4)[0] == 480
        assert self.dsi.read(self.base + 0x50, 4)[0] == 480

    def test_ghcr_write(self):
        """GHCR write should not crash (command processing)."""
        # DCS Short Write, 1 parameter, VC=0
        ghcr = 0x15 | (0 << 6) | (0x36 << 8) | (0x48 << 16)
        self.dsi.write(self.base + 0x6C, 4, ghcr)
        # GHCR is write-only, read returns 0
        assert self.dsi.read(self.base + 0x6C, 4)[0] == 0

    def test_mcr_default(self):
        """MCR defaults to command mode (1)."""
        assert self.dsi.read(self.base + 0x34, 4)[0] == 1

    def test_ccr(self):
        self.dsi.write(self.base + 0x08, 4, 0x0502)
        assert self.dsi.read(self.base + 0x08, 4)[0] == 0x0502

    def test_ier0_ier1(self):
        self.dsi.write(self.base + 0xC4, 4, 0xFF)  # IER0
        self.dsi.write(self.base + 0xC8, 4, 0xAA)  # IER1
        assert self.dsi.read(self.base + 0xC4, 4)[0] == 0xFF
        assert self.dsi.read(self.base + 0xC8, 4)[0] == 0xAA


# ---------------------------------------------------------------------------
# U5A9 peripheral set tests
# ---------------------------------------------------------------------------

class TestU5A9PeripheralSet:
    """Test STM32U5A9 peripheral set instantiation."""

    def test_instantiation(self):
        pset = STM32U5A9PeripheralSet()
        assert pset.device == "STM32U5A9"

    def test_has_dsi(self):
        pset = STM32U5A9PeripheralSet()
        assert hasattr(pset, 'dsi')
        assert pset.dsi.name == "DSI"

    def test_has_ltdc(self):
        pset = STM32U5A9PeripheralSet()
        assert hasattr(pset, 'ltdc')
        assert pset.ltdc.name == "LTDC"

    def test_has_sdmmc(self):
        pset = STM32U5A9PeripheralSet()
        assert hasattr(pset, 'sdmmc1')
        assert hasattr(pset, 'sdmmc2')
        assert pset.sdmmc1.name == "SDMMC1"

    def test_more_peripherals_than_u5a5(self):
        u5a5 = STM32U5A5PeripheralSet()
        u5a9 = STM32U5A9PeripheralSet()
        # U5A9 should have DSI + LTDC extra
        assert len(u5a9.peripherals) == len(u5a5.peripherals) + 2

    def test_u5a5_has_sdmmc(self):
        """U5A5 base also has SDMMC (added to base class)."""
        pset = STM32U5A5PeripheralSet()
        assert hasattr(pset, 'sdmmc1')
        assert hasattr(pset, 'sdmmc2')

    def test_u5a5_no_dsi(self):
        """U5A5 should NOT have DSI or LTDC."""
        pset = STM32U5A5PeripheralSet()
        assert not hasattr(pset, 'dsi')
        assert not hasattr(pset, 'ltdc')
