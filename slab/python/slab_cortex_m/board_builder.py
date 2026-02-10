"""
Board Builder

Factory that takes a BoardConfig and produces an assembled board:
peripheral set (adapted) + external devices (wired).

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional

from slab_cortex_m.board import (
    BoardConfig, ExternalDevice, create_peripheral_set,
    get_qemu_cpu, get_default_clock,
)
from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter

log = logging.getLogger('BoardBuilder')


class Board:
    """An assembled board: adapted peripheral set + external devices."""

    def __init__(self, config: BoardConfig, adapter: PeripheralSetAdapter):
        self.config = config
        self.adapter = adapter
        self.external_devices = []
        self.bus_devices: dict = {}  # "SPI1" -> [W25QxxFlash, ...]
        self.name = config.name
        self.qemu_cpu = get_qemu_cpu(config)
        self.clock = get_default_clock(config)
        self.uart_output = bytearray()
        self.usb_transactions: list = []
        self.led_states = {}

    def find_peripheral(self, addr: int):
        return self.adapter.find_peripheral(addr)

    def read(self, addr: int, size: int, secure: bool = True):
        return self.adapter.read(addr, size, secure)

    def write(self, addr: int, size: int, value: int, secure: bool = True):
        return self.adapter.write(addr, size, value, secure)

    def contains(self, addr: int) -> bool:
        return self.adapter.contains(addr)

    @property
    def irq_callback(self):
        return self.adapter.irq_callback

    @irq_callback.setter
    def irq_callback(self, cb):
        self.adapter.irq_callback = cb


class _I2CDeviceAdapter:
    """Bridges STM32 I2C byte-level callbacks to EEPROM_24Cxx packet protocol."""

    def __init__(self, device):
        self.device = device
        self._write_buf = bytearray()
        self._is_read = False

    def on_start(self, addr_7bit: int, is_read: bool):
        addr_8bit = (addr_7bit << 1) | (1 if is_read else 0)
        self._is_read = is_read
        self._write_buf.clear()
        self.device.i2c_start(addr_8bit, is_read)

    def on_write(self, byte: int):
        self._write_buf.append(byte)

    def on_read(self) -> int:
        data = self.device.i2c_read(1)
        return data[0] if data else 0xFF

    def on_stop(self):
        if self._write_buf:
            self.device.i2c_write(bytes(self._write_buf))
            self._write_buf.clear()


def _find_peripheral(board: Board, name: str):
    """Find a peripheral by name in the adapted set."""
    for p in board.adapter.peripherals:
        if hasattr(p, 'name') and p.name == name:
            return p
    return None


def _create_external_device(device_cfg: ExternalDevice):
    """Create a virtual external device from config."""
    dtype = device_cfg.type.upper()

    if dtype == 'LED':
        log.info(f"LED on {device_cfg.bus} pin {device_cfg.params.get('pin', 0)}")
        return None

    elif dtype in ('W25Q128', 'W25Q64', 'W25Q32', 'W25Q16', 'W25Q256'):
        from slab_cortex_m.virtual_components import W25QxxFlash
        flash = W25QxxFlash(model=dtype)
        log.info(f"Created {dtype} flash on {device_cfg.bus}")
        return flash

    elif dtype in ('24C256', '24C512', '24C64', '24C32', '24C128', '24C16',
                   '24C08', '24C04', '24C02'):
        from slab_cortex_m.virtual_components import EEPROM_24Cxx
        eeprom = EEPROM_24Cxx(
            model=dtype,
            address=device_cfg.params.get('address', 0x50),
        )
        log.info(f"Created {dtype} EEPROM on {device_cfg.bus} "
                 f"@ 0x{eeprom.address:02X}")
        return eeprom

    elif dtype == 'ILI9341':
        from slab_cortex_m.virtual_components import ILI9341_LCD
        lcd = ILI9341_LCD(name="ILI9341")
        log.info(f"Created ILI9341 LCD on {device_cfg.bus}")
        return lcd

    elif dtype == 'SSD1306':
        from slab_cortex_m.virtual_components import SSD1306_OLED
        oled = SSD1306_OLED(
            address=device_cfg.params.get('address', 0x3C),
            name="SSD1306",
        )
        log.info(f"Created SSD1306 OLED on {device_cfg.bus}")
        return oled

    else:
        log.warning(f"Unknown external device type: {device_cfg.type}")
        return None


def _wire_device(board: Board, device_cfg: ExternalDevice, device):
    """Wire an external device to the appropriate bus peripheral."""
    if device is None:
        return

    bus_name = device_cfg.bus
    p = _find_peripheral(board, bus_name)
    if p is None:
        log.warning(f"Bus peripheral '{bus_name}' not found for {device_cfg.type}")
        return

    dtype = device_cfg.type.upper()
    cls_name = type(p).__name__

    if dtype.startswith('W25Q'):
        _wire_spi_flash(p, device, cls_name, bus_name, dtype)
    elif dtype.startswith('24C'):
        _wire_i2c_eeprom(p, device, cls_name, bus_name, dtype)
    elif dtype == 'ILI9341':
        _wire_spi_display(p, device, cls_name, bus_name, dtype)
    elif dtype == 'SSD1306':
        _wire_i2c_display(p, device, cls_name, bus_name, dtype)


def _wire_spi_flash(p, device, cls_name: str, bus_name: str, dtype: str):
    """Wire SPI flash to a bus peripheral."""
    if 'QSPI' in cls_name or bus_name == 'QSPI':
        # NRF QSPI: wire flash access and custom instruction callbacks
        if hasattr(p, 'on_flash_access'):
            def qspi_flash_access(op, addr, data):
                device.select()
                if op == 'read':
                    cmd = bytes([0x03]) + addr.to_bytes(3, 'big') + bytes(len(data))
                    result = device.transfer(cmd)
                    device.deselect()
                    return result[4:]
                elif op == 'write':
                    cmd = bytes([0x06])
                    device.transfer(cmd)
                    cmd = bytes([0x02]) + addr.to_bytes(3, 'big') + data
                    device.transfer(cmd)
                    device.deselect()
                    return b''
                elif op == 'erase_4k':
                    cmd = bytes([0x06])
                    device.transfer(cmd)
                    cmd = bytes([0x20]) + addr.to_bytes(3, 'big')
                    device.transfer(cmd)
                    device.deselect()
                    return b''
                else:
                    device.deselect()
                    return b''
            p.on_flash_access = qspi_flash_access
            log.info(f"Wired {dtype} to {bus_name}.on_flash_access")

        if hasattr(p, 'on_custom_instruction'):
            def qspi_custom_instr(opcode, data_in):
                device.select()
                cmd = bytes([opcode]) + (data_in or b'')
                result = device.transfer(cmd + bytes(8))
                device.deselect()
                return result[1:]
            p.on_custom_instruction = qspi_custom_instr
            log.info(f"Wired {dtype} to {bus_name}.on_custom_instruction")

    elif 'SPIM' in cls_name or 'NRF' in cls_name:
        # NRF SPIM: packet-level on_transfer(bytes) -> bytes
        if hasattr(p, 'on_transfer'):
            def spim_transfer(mosi):
                device.select()
                result = device.transfer(mosi)
                device.deselect()
                return result
            p.on_transfer = spim_transfer
            log.info(f"Wired {dtype} to {bus_name}.on_transfer (packet)")

    elif hasattr(p, 'on_transfer'):
        # STM32 SPI: byte-level on_transfer(int) -> int
        p.on_transfer = device.transfer_byte
        log.info(f"Wired {dtype} to {bus_name}.on_transfer (byte)")


def _wire_i2c_eeprom(p, device, cls_name: str, bus_name: str, dtype: str):
    """Wire I2C EEPROM to a bus peripheral."""
    if 'TWIM' in cls_name or 'NRF' in cls_name:
        # NRF TWIM: on_transfer(addr, data, is_read) -> bytes
        if hasattr(p, 'on_transfer'):
            def twim_transfer(addr, data, is_read):
                addr_8bit = (addr << 1) | (1 if is_read else 0)
                device.i2c_start(addr_8bit, is_read)
                if is_read:
                    return device.i2c_read(len(data) if data else 256)
                else:
                    device.i2c_write(data)
                    return b''
            p.on_transfer = twim_transfer
            log.info(f"Wired {dtype} to {bus_name}.on_transfer (TWIM)")

    elif hasattr(p, 'on_start'):
        # STM32 I2C: byte-level callbacks
        adapter = _I2CDeviceAdapter(device)
        p.on_start = adapter.on_start
        p.on_write = adapter.on_write
        p.on_read = adapter.on_read
        p.on_stop = adapter.on_stop
        log.info(f"Wired {dtype} to {bus_name} via I2C adapter")


def _wire_spi_display(p, device, cls_name: str, bus_name: str, dtype: str):
    """Wire SPI display (ILI9341) to a bus peripheral."""
    if 'SPIM' in cls_name or 'NRF' in cls_name:
        if hasattr(p, 'on_transfer'):
            def spim_display(mosi):
                device.select()
                result = device.transfer(mosi)
                device.deselect()
                return result
            p.on_transfer = spim_display
            log.info(f"Wired {dtype} to {bus_name}.on_transfer (packet)")
    elif hasattr(p, 'on_transfer'):
        # STM32 SPI byte-level: ILI9341.transfer() iterates bytes internally,
        # but on_transfer is called per-byte from STM32 SPI DR write.
        # ILI9341 already processes byte-by-byte via _process_byte.
        def spi_display_byte(mosi_byte):
            device._process_byte(mosi_byte)
            return 0xFF
        p.on_transfer = spi_display_byte
        log.info(f"Wired {dtype} to {bus_name}.on_transfer (byte)")


def _wire_i2c_display(p, device, cls_name: str, bus_name: str, dtype: str):
    """Wire I2C display (SSD1306) to a bus peripheral."""
    if 'TWIM' in cls_name or 'NRF' in cls_name:
        if hasattr(p, 'on_transfer'):
            def twim_display(addr, data, is_read):
                addr_8bit = (addr << 1) | (1 if is_read else 0)
                device.i2c_start(addr_8bit, is_read)
                if is_read:
                    return device.i2c_read(len(data) if data else 1)
                else:
                    device.i2c_write(data)
                    return b''
            p.on_transfer = twim_display
            log.info(f"Wired {dtype} to {bus_name}.on_transfer (TWIM)")
    elif hasattr(p, 'on_start'):
        adapter = _I2CDeviceAdapter(device)
        p.on_start = adapter.on_start
        p.on_write = adapter.on_write
        p.on_read = adapter.on_read
        p.on_stop = adapter.on_stop
        log.info(f"Wired {dtype} to {bus_name} via I2C adapter")


def _wire_uart(board: Board):
    """Wire USART/UART on_tx callbacks to capture output."""
    for p in board.adapter.peripherals:
        name = getattr(p, 'name', '')
        if ('USART' in name or 'UART' in name or 'UARTE' in name) \
                and hasattr(p, 'on_tx'):
            pname = name  # capture for closure

            def make_tx_handler(periph_name):
                def tx_handler(byte):
                    board.uart_output.append(byte & 0xFF)
                return tx_handler

            p.on_tx = make_tx_handler(pname)
            log.debug(f"Wired {pname}.on_tx to board.uart_output")


def _wire_leds(board: Board):
    """Wire LED GPIO pin-change callbacks for tracking."""
    for dev_cfg in board.config.external_devices:
        if dev_cfg.type.upper() != 'LED':
            continue

        gpio_name = dev_cfg.bus
        pin = dev_cfg.params.get('pin', 0)
        color = dev_cfg.params.get('color', 'unknown')
        key = f"{gpio_name}:{pin}"
        board.led_states[key] = {'color': color, 'state': False}

        p = _find_peripheral(board, gpio_name)
        if p is None:
            log.debug(f"GPIO '{gpio_name}' not found for LED pin {pin}")
            continue

        if hasattr(p, 'on_pin_change'):
            existing_cb = p.on_pin_change

            def make_pin_handler(led_key, led_pin, prev_cb):
                def pin_handler(changed_pin, value, is_output):
                    if changed_pin == led_pin:
                        board.led_states[led_key]['state'] = bool(value)
                    if prev_cb:
                        prev_cb(changed_pin, value, is_output)
                return pin_handler

            p.on_pin_change = make_pin_handler(key, pin, existing_cb)
            log.debug(f"Wired LED {color} on {key}")


def build_board(config: BoardConfig) -> Board:
    """Build a complete board from configuration.

    1. Create MCU peripheral set
    2. Wrap in PeripheralSetAdapter
    3. Create and wire external devices
    4. Wire UART console capture
    5. Wire LED GPIO tracking
    """
    # Create peripheral set
    pset = create_peripheral_set(config)

    # Wrap in adapter
    adapter = PeripheralSetAdapter(pset)
    board = Board(config, adapter)

    # Create and wire external devices
    for dev_cfg in config.external_devices:
        device = _create_external_device(dev_cfg)
        if device:
            board.external_devices.append(device)
            board.bus_devices.setdefault(dev_cfg.bus, []).append(device)
            _wire_device(board, dev_cfg, device)

    # Wire UART console output capture
    _wire_uart(board)

    # Wire LED GPIO tracking
    _wire_leds(board)

    log.info(f"Board '{config.name}' ready: {len(adapter.peripherals)} peripherals, "
             f"{len(board.external_devices)} external devices")

    return board
