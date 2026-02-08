"""
NRF RADIO - 2.4GHz Radio Transceiver

Supports:
- BLE (Bluetooth Low Energy)
- IEEE 802.15.4 (Thread, Zigbee)
- Proprietary protocols

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable, List
from .nrf_base import NRFPeripheral


class NRFRADIO(NRFPeripheral):
    """NRF 2.4GHz Radio."""

    # Tasks
    TASKS_TXEN = 0x000
    TASKS_RXEN = 0x004
    TASKS_START = 0x008
    TASKS_STOP = 0x00C
    TASKS_DISABLE = 0x010
    TASKS_RSSISTART = 0x014
    TASKS_RSSISTOP = 0x018
    TASKS_BCSTART = 0x01C
    TASKS_BCSTOP = 0x020
    TASKS_EDSTART = 0x024
    TASKS_EDSTOP = 0x028
    TASKS_CCASTART = 0x02C
    TASKS_CCASTOP = 0x030

    # Events
    EVENTS_READY = 0x100
    EVENTS_ADDRESS = 0x104
    EVENTS_PAYLOAD = 0x108
    EVENTS_END = 0x10C
    EVENTS_DISABLED = 0x110
    EVENTS_DEVMATCH = 0x114
    EVENTS_DEVMISS = 0x118
    EVENTS_RSSIEND = 0x11C
    EVENTS_BCMATCH = 0x128
    EVENTS_CRCOK = 0x130
    EVENTS_CRCERROR = 0x134
    EVENTS_FRAMESTART = 0x138
    EVENTS_EDEND = 0x13C
    EVENTS_EDSTOPPED = 0x140
    EVENTS_CCAIDLE = 0x144
    EVENTS_CCABUSY = 0x148
    EVENTS_CCASTOPPED = 0x14C
    EVENTS_RATEBOOST = 0x150
    EVENTS_TXREADY = 0x154
    EVENTS_RXREADY = 0x158
    EVENTS_MHRMATCH = 0x15C
    EVENTS_PHYEND = 0x16C

    # Registers
    PACKETPTR = 0x504
    FREQUENCY = 0x508
    TXPOWER = 0x50C
    MODE = 0x510
    PCNF0 = 0x514
    PCNF1 = 0x518
    BASE0 = 0x51C
    BASE1 = 0x520
    PREFIX0 = 0x524
    PREFIX1 = 0x528
    TXADDRESS = 0x52C
    RXADDRESSES = 0x530
    CRCCNF = 0x534
    CRCPOLY = 0x538
    CRCINIT = 0x53C
    TIFS = 0x544
    RSSISAMPLE = 0x548
    STATE = 0x550
    DATAWHITEIV = 0x554
    BCC = 0x560
    DAB_BASE = 0x600
    DAP_BASE = 0x620
    DACNF = 0x640
    MHRMATCHCONF = 0x644
    MHRMATCHMAS = 0x648
    MODECNF0 = 0x650
    SFD = 0x660
    EDCNT = 0x664
    EDSAMPLE = 0x668
    CCACTRL = 0x66C
    DFEMODE = 0x900
    CTEINLINECONF = 0x904
    POWER = 0xFFC

    # State values
    STATE_DISABLED = 0
    STATE_RXRU = 1
    STATE_RXIDLE = 2
    STATE_RX = 3
    STATE_RXDISABLE = 4
    STATE_TXRU = 9
    STATE_TXIDLE = 10
    STATE_TX = 11
    STATE_TXDISABLE = 12

    # Mode values
    MODE_NRF_1MBIT = 0
    MODE_NRF_2MBIT = 1
    MODE_BLE_1MBIT = 3
    MODE_BLE_2MBIT = 4
    MODE_BLE_LR125 = 5
    MODE_BLE_LR500 = 6
    MODE_IEEE802154 = 15

    def __init__(self, base: int = 0x40001000):
        super().__init__("RADIO", base, 0x1000, irq=1)

        self.packetptr = 0
        self.frequency = 2  # 2402 MHz (BLE advertising ch 37)
        self.txpower = 0  # 0 dBm
        self.mode = self.MODE_BLE_1MBIT
        self.pcnf0 = 0
        self.pcnf1 = 0
        self.base0 = 0
        self.base1 = 0
        self.prefix0 = 0
        self.prefix1 = 0
        self.txaddress = 0
        self.rxaddresses = 0
        self.crccnf = 0
        self.crcpoly = 0
        self.crcinit = 0
        self.tifs = 0
        self.datawhiteiv = 0
        self.state = self.STATE_DISABLED
        self.rssisample = 0
        self.power = 1

        # Received packet buffer
        self.rx_buffer: List[bytes] = []

        # Callbacks
        self.mem_read: Optional[Callable[[int, int], bytes]] = None
        self.mem_write: Optional[Callable[[int, bytes], None]] = None
        self.on_tx: Optional[Callable[[bytes], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        regs = {
            self.PACKETPTR: self.packetptr,
            self.FREQUENCY: self.frequency,
            self.TXPOWER: self.txpower,
            self.MODE: self.mode,
            self.PCNF0: self.pcnf0,
            self.PCNF1: self.pcnf1,
            self.BASE0: self.base0,
            self.BASE1: self.base1,
            self.PREFIX0: self.prefix0,
            self.PREFIX1: self.prefix1,
            self.TXADDRESS: self.txaddress,
            self.RXADDRESSES: self.rxaddresses,
            self.CRCCNF: self.crccnf,
            self.CRCPOLY: self.crcpoly,
            self.CRCINIT: self.crcinit,
            self.TIFS: self.tifs,
            self.STATE: self.state,
            self.RSSISAMPLE: self.rssisample,
            self.DATAWHITEIV: self.datawhiteiv,
            self.POWER: self.power,
        }
        return regs.get(offset, self.regs.get(offset, 0))

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.PACKETPTR:
            self.packetptr = value
        elif offset == self.FREQUENCY:
            self.frequency = value
        elif offset == self.TXPOWER:
            self.txpower = value
        elif offset == self.MODE:
            self.mode = value
        elif offset == self.PCNF0:
            self.pcnf0 = value
        elif offset == self.PCNF1:
            self.pcnf1 = value
        elif offset == self.BASE0:
            self.base0 = value
        elif offset == self.BASE1:
            self.base1 = value
        elif offset == self.PREFIX0:
            self.prefix0 = value
        elif offset == self.PREFIX1:
            self.prefix1 = value
        elif offset == self.TXADDRESS:
            self.txaddress = value
        elif offset == self.RXADDRESSES:
            self.rxaddresses = value
        elif offset == self.CRCCNF:
            self.crccnf = value
        elif offset == self.CRCPOLY:
            self.crcpoly = value
        elif offset == self.CRCINIT:
            self.crcinit = value
        elif offset == self.TIFS:
            self.tifs = value
        elif offset == self.DATAWHITEIV:
            self.datawhiteiv = value
        elif offset == self.POWER:
            self.power = value & 1
        else:
            self.regs[offset] = value

    def _handle_task(self, offset: int):
        if offset == self.TASKS_TXEN:
            self.state = self.STATE_TXRU
            self.set_event(self.EVENTS_READY)
            self.set_event(self.EVENTS_TXREADY)
            self.state = self.STATE_TXIDLE
        elif offset == self.TASKS_RXEN:
            self.state = self.STATE_RXRU
            self.set_event(self.EVENTS_READY)
            self.set_event(self.EVENTS_RXREADY)
            self.state = self.STATE_RXIDLE
        elif offset == self.TASKS_START:
            self._start()
        elif offset == self.TASKS_STOP:
            self._stop()
        elif offset == self.TASKS_DISABLE:
            self._disable()
        elif offset == self.TASKS_RSSISTART:
            self.rssisample = 60  # -60 dBm typical
            self.set_event(self.EVENTS_RSSIEND)

    def _start(self):
        """Start TX or RX."""
        if self.state == self.STATE_TXIDLE:
            self.state = self.STATE_TX
            self._do_tx()
        elif self.state == self.STATE_RXIDLE:
            self.state = self.STATE_RX
            self._do_rx()

    def _stop(self):
        """Stop TX or RX."""
        if self.state == self.STATE_TX:
            self.state = self.STATE_TXIDLE
        elif self.state == self.STATE_RX:
            self.state = self.STATE_RXIDLE

    def _disable(self):
        """Disable radio."""
        self.state = self.STATE_DISABLED
        self.set_event(self.EVENTS_DISABLED)

    def _do_tx(self):
        """Transmit packet."""
        if self.mem_read and self.packetptr:
            # Get packet length from PCNF1
            maxlen = (self.pcnf1 >> 0) & 0xFF
            data = self.mem_read(self.packetptr, maxlen + 2)

            if self.on_tx:
                self.on_tx(data)

        self.set_event(self.EVENTS_ADDRESS)
        self.set_event(self.EVENTS_PAYLOAD)
        self.set_event(self.EVENTS_END)
        self.set_event(self.EVENTS_PHYEND)
        self.state = self.STATE_TXIDLE

    def _do_rx(self):
        """Receive packet (check buffer)."""
        if self.rx_buffer:
            packet = self.rx_buffer.pop(0)
            if self.mem_write and self.packetptr:
                self.mem_write(self.packetptr, packet)
            self.set_event(self.EVENTS_ADDRESS)
            self.set_event(self.EVENTS_PAYLOAD)
            self.set_event(self.EVENTS_END)
            self.set_event(self.EVENTS_CRCOK)
            self.state = self.STATE_RXIDLE

    def inject_packet(self, packet: bytes):
        """Inject received packet from external source."""
        self.rx_buffer.append(packet)
        if self.state == self.STATE_RX:
            self._do_rx()

    def get_frequency_mhz(self) -> int:
        """Get actual frequency in MHz."""
        return 2400 + self.frequency
