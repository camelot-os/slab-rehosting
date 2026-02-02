"""
NRF5340 Peripheral Sets

Dual-core architecture:
- Application core: Cortex-M33 @ 128 MHz (TrustZone)
- Network core: Cortex-M33 @ 64 MHz (BLE/802.15.4)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from .nrf_base import NRFPeripheralSet, NRFPeripheral
from .nrf_gpio import NRFGPIO, NRFGPIOTE
from .nrf_uart import NRFUARTE
from .nrf_spi import NRFSPIM
from .nrf_twi import NRFTWIM
from .nrf_timer import NRFTIMER, NRFRTC
from .nrf_saadc import NRFSAADC
from .nrf_nvmc import NRFNVMC
from .nrf_power import NRFPOWER, NRFCLOCK
from .nrf_rng import NRFRNG
from .nrf_crypto import NRFECB, NRFCCM
from .nrf_radio import NRFRADIO


class NRFIPC(NRFPeripheral):
    """NRF5340 Inter-Processor Communication."""

    TASKS_SEND_BASE = 0x000   # [0-15]
    EVENTS_RECEIVE_BASE = 0x100  # [0-15]
    SEND_CNF_BASE = 0x510
    RECEIVE_CNF_BASE = 0x590
    GPMEM_BASE = 0x660  # 2 x 32-bit general purpose memory

    def __init__(self, base: int):
        super().__init__("IPC", base, 0x1000)
        self.send_cnf = [0] * 16
        self.receive_cnf = [0] * 16
        self.gpmem = [0, 0]

    def _read_reg(self, offset: int, size: int) -> int:
        if self.SEND_CNF_BASE <= offset < self.SEND_CNF_BASE + 64:
            idx = (offset - self.SEND_CNF_BASE) // 4
            return self.send_cnf[idx] if idx < 16 else 0
        elif self.RECEIVE_CNF_BASE <= offset < self.RECEIVE_CNF_BASE + 64:
            idx = (offset - self.RECEIVE_CNF_BASE) // 4
            return self.receive_cnf[idx] if idx < 16 else 0
        elif self.GPMEM_BASE <= offset < self.GPMEM_BASE + 8:
            idx = (offset - self.GPMEM_BASE) // 4
            return self.gpmem[idx]
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if self.SEND_CNF_BASE <= offset < self.SEND_CNF_BASE + 64:
            idx = (offset - self.SEND_CNF_BASE) // 4
            if idx < 16:
                self.send_cnf[idx] = value
        elif self.RECEIVE_CNF_BASE <= offset < self.RECEIVE_CNF_BASE + 64:
            idx = (offset - self.RECEIVE_CNF_BASE) // 4
            if idx < 16:
                self.receive_cnf[idx] = value
        elif self.GPMEM_BASE <= offset < self.GPMEM_BASE + 8:
            idx = (offset - self.GPMEM_BASE) // 4
            if idx < 2:
                self.gpmem[idx] = value

    def _handle_task(self, offset: int):
        if self.TASKS_SEND_BASE <= offset < self.TASKS_SEND_BASE + 64:
            ch = (offset - self.TASKS_SEND_BASE) // 4
            # Would signal other core
            pass


class NRFMUTEX(NRFPeripheral):
    """NRF5340 Mutex for multi-core synchronization."""

    def __init__(self, base: int = 0x40030000):
        super().__init__("MUTEX", base, 0x1000)
        self.mutex = [0] * 16

    def _read_reg(self, offset: int, size: int) -> int:
        if 0x400 <= offset < 0x400 + 64:
            idx = (offset - 0x400) // 4
            if idx < 16:
                # Return 0 if free, 1 if locked (and take lock)
                if self.mutex[idx] == 0:
                    self.mutex[idx] = 1
                    return 0
                return 1
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if 0x400 <= offset < 0x400 + 64:
            idx = (offset - 0x400) // 4
            if idx < 16 and value == 0:
                self.mutex[idx] = 0


class NRF5340AppPeripheralSet(NRFPeripheralSet):
    """
    NRF5340 Application Core peripheral set.

    Features:
    - Cortex-M33 @ 128 MHz with TrustZone
    - 1MB Flash, 512KB RAM
    - Full peripheral set
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__("NRF5340_APP", log)

        self._create_system()
        self._create_gpio()
        self._create_communication()
        self._create_timers()
        self._create_analog()
        self._create_multicore()

    def _create_system(self):
        """Create system peripherals."""
        # Application core peripherals at 0x50000000 (secure) or 0x40000000 (non-secure)
        self.power = NRFPOWER(base=0x50005000)
        self.clock = NRFCLOCK(base=0x50005000)
        self.nvmc = NRFNVMC(base=0x50039000)

        self.add_peripheral(self.power)
        self.add_peripheral(self.clock)
        self.add_peripheral(self.nvmc)

    def _create_gpio(self):
        """Create GPIO peripherals."""
        # Application core controls P0 and P1
        self.gpio0 = NRFGPIO(port=0, base=0x50842500)
        self.gpio1 = NRFGPIO(port=1, base=0x50842800)
        self.gpiote = NRFGPIOTE(base=0x5000D000)
        self.gpiote.gpio_ports = [self.gpio0, self.gpio1]

        self.add_peripheral(self.gpio0)
        self.add_peripheral(self.gpio1)
        self.add_peripheral(self.gpiote)

    def _create_communication(self):
        """Create communication peripherals."""
        # UARTE0-3 on application core
        for i in range(4):
            uarte = NRFUARTE(index=i, base=0x50008000 + i * 0x1000)
            setattr(self, f"uarte{i}", uarte)
            self.add_peripheral(uarte)

        # SPIM0-4
        for i in range(5):
            spim = NRFSPIM(index=i, base=0x50008000 + i * 0x1000)
            setattr(self, f"spim{i}", spim)
            self.add_peripheral(spim)

        # TWIM0-3
        for i in range(4):
            twim = NRFTWIM(index=i, base=0x50008000 + i * 0x1000)
            setattr(self, f"twim{i}", twim)
            self.add_peripheral(twim)

    def _create_timers(self):
        """Create timer peripherals."""
        for i in range(3):
            timer = NRFTIMER(index=i, base=0x5000F000 + i * 0x1000)
            setattr(self, f"timer{i}", timer)
            self.add_peripheral(timer)

        for i in range(2):
            rtc = NRFRTC(index=i, base=0x50014000 + i * 0x1000)
            setattr(self, f"rtc{i}", rtc)
            self.add_peripheral(rtc)

    def _create_analog(self):
        """Create analog peripherals."""
        self.saadc = NRFSAADC(base=0x5000E000)
        self.add_peripheral(self.saadc)

    def _create_multicore(self):
        """Create multi-core peripherals."""
        self.ipc = NRFIPC(base=0x5002A000)
        self.mutex = NRFMUTEX(base=0x50030000)
        self.add_peripheral(self.ipc)
        self.add_peripheral(self.mutex)


class NRF5340NetPeripheralSet(NRFPeripheralSet):
    """
    NRF5340 Network Core peripheral set.

    Features:
    - Cortex-M33 @ 64 MHz (no TrustZone)
    - 256KB Flash, 64KB RAM
    - Radio and crypto peripherals
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__("NRF5340_NET", log)

        self._create_system()
        self._create_communication()
        self._create_timers()
        self._create_security()
        self._create_radio()
        self._create_multicore()

    def _create_system(self):
        """Create system peripherals."""
        # Network core peripherals at 0x41000000
        self.power = NRFPOWER(base=0x41005000)
        self.clock = NRFCLOCK(base=0x41005000)
        self.nvmc = NRFNVMC(base=0x41080000)

        self.add_peripheral(self.power)
        self.add_peripheral(self.clock)
        self.add_peripheral(self.nvmc)

    def _create_communication(self):
        """Create communication peripherals."""
        self.uarte0 = NRFUARTE(index=0, base=0x41013000)
        self.spim0 = NRFSPIM(index=0, base=0x41013000)
        self.twim0 = NRFTWIM(index=0, base=0x41013000)

        self.add_peripheral(self.uarte0)
        self.add_peripheral(self.spim0)
        self.add_peripheral(self.twim0)

    def _create_timers(self):
        """Create timer peripherals."""
        self.timer0 = NRFTIMER(index=0, base=0x4100F000)
        self.timer1 = NRFTIMER(index=1, base=0x41010000)
        self.timer2 = NRFTIMER(index=2, base=0x41011000)
        self.rtc0 = NRFRTC(index=0, base=0x41014000)
        self.rtc1 = NRFRTC(index=1, base=0x41016000)

        self.add_peripheral(self.timer0)
        self.add_peripheral(self.timer1)
        self.add_peripheral(self.timer2)
        self.add_peripheral(self.rtc0)
        self.add_peripheral(self.rtc1)

    def _create_security(self):
        """Create security peripherals."""
        self.rng = NRFRNG(base=0x41009000)
        self.ecb = NRFECB(base=0x4100B000)
        self.ccm = NRFCCM(base=0x4100A000)

        self.add_peripheral(self.rng)
        self.add_peripheral(self.ecb)
        self.add_peripheral(self.ccm)

    def _create_radio(self):
        """Create radio peripheral."""
        self.radio = NRFRADIO(base=0x41008000)
        self.add_peripheral(self.radio)

    def _create_multicore(self):
        """Create multi-core peripherals."""
        self.ipc = NRFIPC(base=0x41012000)
        self.add_peripheral(self.ipc)
