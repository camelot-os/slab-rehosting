#!/usr/bin/env python3
"""
CDC-ACM Bridge: Peripheral <-> USBIP

Bridges the USB CDC peripheral (DWC2 OTG register-level emulation) to the
USBIP server (host-facing USB/IP protocol). This allows firmware running
on the slab-cortex-m QEMU machine to expose a working CDC-ACM device
visible via lsusb on the host (or in a Docker container).

Data flow:
    Firmware TX (EP1 FIFO write) --> CDCBridge --> USBIP tx_buffer --> Host IN
    Host OUT (USBIP data_out)    --> CDCBridge --> Peripheral rx_buffer --> Firmware RX

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CDCBridge:
    """
    Bridge between USBCDCPeripheral and CDCACMDevice (USBIP).

    Replaces the default echo-mode behavior in both components with
    a proper cross-connection:
    - Firmware EP1 TX data -> USBIP host IN endpoint
    - USBIP host OUT data -> Firmware EP1 RX buffer
    """

    def __init__(self, cdc_peripheral, usbip_device):
        """
        Initialize the CDC bridge.

        Args:
            cdc_peripheral: USBCDCPeripheral instance (register-level emulation)
            usbip_device: CDCACMDevice instance (USBIP protocol handler)
        """
        self.cdc = cdc_peripheral
        self.usbip_dev = usbip_device
        self.log = logging.getLogger('CDCBridge')

        # Patch the peripheral's EP1 TX handler to forward to USBIP
        self._original_handle_tx = self.cdc.handle_tx_data
        self.cdc.handle_tx_data = self._handle_firmware_tx

        # Patch the USBIP device's data_out handler to forward to peripheral
        self._original_data_out = self.usbip_dev.handle_data_out
        self.usbip_dev.handle_data_out = self._handle_host_out

        self.log.info("CDC bridge active: peripheral <-> USBIP")

    def _handle_firmware_tx(self, ep: int, value: int):
        """
        Handle firmware TX FIFO write.

        EP0: control data (pass through to original handler)
        EP1: CDC data -> forward to USBIP tx_buffer for host consumption
        """
        if ep == 0:
            # EP0 control data - use original handler
            self._original_handle_tx(ep, value)
        elif ep == 1:
            # CDC data endpoint - forward to USBIP instead of echo
            for i in range(4):
                byte = (value >> (i * 8)) & 0xFF
                if byte:  # Skip null padding
                    self.usbip_dev.tx_buffer.append(byte)
            self.log.debug(f"FW->Host: 0x{value:08X}")
        else:
            self._original_handle_tx(ep, value)

    def _handle_host_out(self, ep: int, data: bytes) -> int:
        """
        Handle data received from host via USBIP (OUT transfer).

        DWC2 OUT transfer sequence (per databook §8.4.3):
        1. Core receives data → pushes DATA_UPDT status + data to FIFO
        2. Core completes transfer → pushes XFER_COMP status (no data)
        3. Core sets DOEPINT.XFRC
        """
        if ep == 1:
            # Phase 1: DATA_UPDT (pktsts=0x2) - data available in FIFO
            self.cdc._rx_status_queue.append((ep, 0x2, len(data)))
            self.cdc._rx_data_queue.extend(data)

            # Phase 2: XFER_COMP (pktsts=0x3) - transfer complete notification
            self.cdc._rx_status_queue.append((ep, 0x3, 0))

            # Phase 3: Set DOEPINT.XFRC (bit 0) for endpoint interrupt
            doepint_offset = self.cdc.DOEPINT0 + ep * 0x20
            self.cdc.regs[doepint_offset] = self.cdc.regs.get(doepint_offset, 0) | 0x01

            # Assert IRQ (RXFLVL now pending)
            self.cdc.trigger_irq()
            self.log.debug(f"Host->FW: {data!r} (bcnt={len(data)})")
            return len(data)
        return 0

    def disconnect(self):
        """Restore original handlers."""
        self.cdc.handle_tx_data = self._original_handle_tx
        self.usbip_dev.handle_data_out = self._original_data_out
        self.log.info("CDC bridge disconnected")
