"""
STM32WBxx Peripheral Sets

Supported devices:
- STM32WB55 (BLE 5.0, IEEE 802.15.4, dual core M4+M0+)
- STM32WB35 (BLE only, cost optimized)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Dict, List
from .stm32_base import STM32PeripheralSet, STM32Peripheral
from .stm32_gpio import STM32GPIOv2, STM32EXTI
from .stm32_usart import STM32USARTv2, STM32LPUART
from .stm32_spi import STM32SPIv1
from .stm32_i2c import STM32I2Cv2
from .stm32_rcc import STM32RCCv3
from .stm32_dma import STM32DMAv1
from .stm32_timers import STM32BasicTimer, STM32GeneralTimer, STM32AdvancedTimer, STM32LPTIM
from .stm32_adc import STM32ADCv3
from .stm32_pwr import STM32PWRv2
from .stm32_flash import STM32FLASHv3
from .stm32_misc import STM32SYSCFG, STM32IWDG, STM32WWDG, STM32RTC, STM32CRC, STM32RNG, STM32DBG


class STM32IPCC(STM32Peripheral):
    """
    STM32WB Inter-Processor Communication Controller.

    Used for communication between M4 and M0+ cores.
    """

    C1CR = 0x00     # CPU1 control
    C1MR = 0x04     # CPU1 mask
    C1SCR = 0x08    # CPU1 status clear
    C1TOC2SR = 0x0C # CPU1 to CPU2 status
    C2CR = 0x10     # CPU2 control
    C2MR = 0x14     # CPU2 mask
    C2SCR = 0x18    # CPU2 status clear
    C2TOC1SR = 0x1C # CPU2 to CPU1 status

    def __init__(self, base: int = 0x58000C00):
        super().__init__("IPCC", base, 0x400)

        self.c1cr = 0
        self.c1mr = 0xFFFFFFFF
        self.c2cr = 0
        self.c2mr = 0xFFFFFFFF
        self.channels = [0] * 6  # 6 channels

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.C1CR:
            return self.c1cr
        elif offset == self.C1MR:
            return self.c1mr
        elif offset == self.C1TOC2SR:
            return self._get_c1_to_c2_status()
        elif offset == self.C2CR:
            return self.c2cr
        elif offset == self.C2MR:
            return self.c2mr
        elif offset == self.C2TOC1SR:
            return self._get_c2_to_c1_status()
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.C1CR:
            self.c1cr = value
        elif offset == self.C1MR:
            self.c1mr = value
        elif offset == self.C1SCR:
            self._clear_c1_status(value)
        elif offset == self.C2CR:
            self.c2cr = value
        elif offset == self.C2MR:
            self.c2mr = value
        elif offset == self.C2SCR:
            self._clear_c2_status(value)

    def _get_c1_to_c2_status(self) -> int:
        status = 0
        for i in range(6):
            if self.channels[i] & 0x01:  # C1 set flag
                status |= (1 << i)
        return status

    def _get_c2_to_c1_status(self) -> int:
        status = 0
        for i in range(6):
            if self.channels[i] & 0x02:  # C2 set flag
                status |= (1 << i)
        return status

    def _clear_c1_status(self, value: int):
        for i in range(6):
            if value & (1 << i):
                self.channels[i] &= ~0x02

    def _clear_c2_status(self, value: int):
        for i in range(6):
            if value & (1 << i):
                self.channels[i] &= ~0x01


class STM32HSEM(STM32Peripheral):
    """
    STM32 Hardware Semaphore.

    32 semaphores for multi-core synchronization.
    """

    def __init__(self, base: int = 0x58001400):
        super().__init__("HSEM", base, 0x400)

        self.semaphores = [0] * 32
        self.rlr = [0] * 32  # Read lock registers
        self.ier = [0, 0]    # Interrupt enable (C1, C2)
        self.isr = [0, 0]    # Interrupt status
        self.keyr = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset < 0x80:
            # Semaphore registers (RLR)
            idx = offset // 4
            if idx < 32:
                return self._read_lock(idx)
        elif offset == 0x100:
            return self.ier[0]
        elif offset == 0x104:
            return self.isr[0]
        elif offset == 0x110:
            return self.ier[1]
        elif offset == 0x114:
            return self.isr[1]
        elif offset == 0x140:
            return self.keyr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset < 0x80:
            idx = offset // 4
            if idx < 32:
                self._write_lock(idx, value)
        elif offset == 0x100:
            self.ier[0] = value
        elif offset == 0x110:
            self.ier[1] = value
        elif offset == 0x140:
            self.keyr = value & 0xFFFF

    def _read_lock(self, idx: int) -> int:
        """Read lock attempt. Returns lock status."""
        if self.semaphores[idx] == 0:
            # Take lock
            self.semaphores[idx] = 1
            return 0  # Success
        return self.semaphores[idx]  # Already locked

    def _write_lock(self, idx: int, value: int):
        """Write to release or take lock."""
        if value == 0:
            # Release
            self.semaphores[idx] = 0
        else:
            # Take (if free)
            if self.semaphores[idx] == 0:
                self.semaphores[idx] = value


class STM32PKA(STM32Peripheral):
    """
    STM32 Public Key Accelerator.

    Supports:
    - RSA (up to 4096-bit)
    - ECC (NIST P-256, P-384, brainpool)
    - ECDSA
    - Modular arithmetic
    """

    CR = 0x00
    SR = 0x04
    CLRFR = 0x08

    # CR bits
    CR_EN = 1 << 0
    CR_START = 1 << 1
    CR_MODE = 0x3F << 8
    CR_PROCENDIE = 1 << 17
    CR_RAMERRIE = 1 << 19
    CR_ADDRERRIE = 1 << 20

    # SR bits
    SR_INITOK = 1 << 0
    SR_BUSY = 1 << 16
    SR_PROCENDF = 1 << 17
    SR_RAMERRF = 1 << 19
    SR_ADDRERRF = 1 << 20

    def __init__(self, base: int = 0x58002000):
        super().__init__("PKA", base, 0x2000)

        self.cr = 0
        self.sr = self.SR_INITOK

        # PKA RAM (for operands and results)
        self.ram = bytearray(4096)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.SR:
            return self.sr
        elif offset >= 0x400:
            # RAM access
            ram_offset = offset - 0x400
            if ram_offset + size <= len(self.ram):
                return int.from_bytes(self.ram[ram_offset:ram_offset+size], 'little')
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self._write_cr(value)
        elif offset == self.CLRFR:
            self.sr &= ~(value & 0x1E0000)
        elif offset >= 0x400:
            # RAM access
            ram_offset = offset - 0x400
            if ram_offset + size <= len(self.ram):
                self.ram[ram_offset:ram_offset+size] = value.to_bytes(size, 'little')

    def _write_cr(self, value: int):
        self.cr = value

        if value & self.CR_START:
            # Start operation (simulated instant completion)
            self.sr |= self.SR_PROCENDF
            self.sr &= ~self.SR_BUSY
            self.cr &= ~self.CR_START


class STM32AES(STM32Peripheral):
    """
    STM32 AES Hardware Accelerator.

    Supports:
    - AES-128, AES-192, AES-256
    - ECB, CBC, CTR, GCM, CCM
    """

    CR = 0x00
    SR = 0x04
    DINR = 0x08
    DOUTR = 0x0C
    KEYR0 = 0x10
    KEYR1 = 0x14
    KEYR2 = 0x18
    KEYR3 = 0x1C
    IVR0 = 0x20
    IVR1 = 0x24
    IVR2 = 0x28
    IVR3 = 0x2C
    KEYR4 = 0x30  # For 256-bit
    KEYR5 = 0x34
    KEYR6 = 0x38
    KEYR7 = 0x3C
    SUSP0R = 0x40  # Suspend registers (for context save)

    # CR bits
    CR_EN = 1 << 0
    CR_DATATYPE = 0x3 << 1
    CR_MODE = 0x3 << 3
    CR_CHMOD = 0x3 << 5
    CR_CCFC = 1 << 7
    CR_ERRC = 1 << 8
    CR_CCFIE = 1 << 9
    CR_ERRIE = 1 << 10
    CR_DMAINEN = 1 << 11
    CR_DMAOUTEN = 1 << 12
    CR_GCMPH = 0x3 << 13
    CR_KEYSIZE = 1 << 18
    CR_NPBLB = 0xF << 20

    # SR bits
    SR_CCF = 1 << 0
    SR_RDERR = 1 << 1
    SR_WRERR = 1 << 2
    SR_BUSY = 1 << 3

    def __init__(self, base: int = 0x58001800):
        super().__init__("AES", base, 0x400)

        self.cr = 0
        self.sr = 0
        self.key = [0] * 8
        self.iv = [0] * 4
        self.din_buf = []
        self.dout_buf = []

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.SR:
            return self.sr
        elif offset == self.DOUTR:
            if self.dout_buf:
                return self.dout_buf.pop(0)
            return 0
        elif self.KEYR0 <= offset <= self.KEYR7:
            idx = (offset - self.KEYR0) // 4
            return self.key[idx] if idx < 8 else 0
        elif self.IVR0 <= offset <= self.IVR3:
            idx = (offset - self.IVR0) // 4
            return self.iv[idx]
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self._write_cr(value)
        elif offset == self.DINR:
            self._write_din(value)
        elif self.KEYR0 <= offset <= self.KEYR7:
            idx = (offset - self.KEYR0) // 4
            if idx < 8:
                self.key[idx] = value
        elif self.IVR0 <= offset <= self.IVR3:
            idx = (offset - self.IVR0) // 4
            self.iv[idx] = value

    def _write_cr(self, value: int):
        if value & self.CR_CCFC:
            self.sr &= ~self.SR_CCF
        if value & self.CR_ERRC:
            self.sr &= ~(self.SR_RDERR | self.SR_WRERR)
        self.cr = value & ~(self.CR_CCFC | self.CR_ERRC)

    def _write_din(self, value: int):
        self.din_buf.append(value)
        # Simulate processing after 4 words (128-bit block)
        if len(self.din_buf) >= 4:
            self._process_block()

    def _process_block(self):
        """Process one AES block (simulated)."""
        # In real implementation, would do AES
        # For emulation, just pass through (or XOR with key for basic simulation)
        self.dout_buf = self.din_buf[:4]
        self.din_buf = self.din_buf[4:]
        self.sr |= self.SR_CCF


class STM32WBxxPeripheralSet(STM32PeripheralSet):
    """
    Base peripheral set for STM32WBxx family.

    Memory Map:
        0x40000000 - APB1 (TIM2, RTC, WWDG, IWDG, SPI2, I2C1/3, LPTIM1/2)
        0x40010000 - APB2 (TIM1/16/17, USART1, SPI1, SAI1)
        0x40020000 - AHB1 (DMA1/2, DMAMUX, CRC)
        0x48000000 - AHB2 (GPIOA-E/H, ADC, AES1)
        0x58000000 - APB3 (RF, IPCC, HSEM, PKA, AES2, RNG, FLASH, PWR, RCC)
    """

    def __init__(self, device: str = "STM32WB55", log: logging.Logger = None):
        super().__init__(device, log)
        self.family = "WB"

        self._create_clock_system()
        self._create_gpio()
        self._create_communication()
        self._create_timers()
        self._create_analog()
        self._create_dma()
        self._create_security()
        self._create_multicore()
        self._create_misc()

    def _create_clock_system(self):
        """Create RCC and related peripherals."""
        self.rcc = STM32RCCv3(base=0x58000000)
        self.rcc.hsi_freq = 16_000_000
        self.add_peripheral(self.rcc)

        self.pwr = STM32PWRv2(base=0x58000400, family="WB")
        self.add_peripheral(self.pwr)

        self.flash = STM32FLASHv3(base=0x58004000, family="L4")
        self.add_peripheral(self.flash)

    def _create_gpio(self):
        """Create GPIO ports."""
        gpio_bases = {
            'A': 0x48000000,
            'B': 0x48000400,
            'C': 0x48000800,
            'D': 0x48000C00,
            'E': 0x48001000,
            'H': 0x48001C00,
        }

        self.gpio = {}
        for port, base in gpio_bases.items():
            self.gpio[port] = STM32GPIOv2(port=port, base=base)
            self.add_peripheral(self.gpio[port])

        self.exti = STM32EXTI(base=0x58000800)
        self.add_peripheral(self.exti)

    def _create_communication(self):
        """Create USART, SPI, I2C peripherals."""
        self.usart1 = STM32USARTv2(index=1, base=0x40013800)
        self.lpuart1 = STM32LPUART(index=1, base=0x40008000)
        self.add_peripheral(self.usart1)
        self.add_peripheral(self.lpuart1)

        self.spi1 = STM32SPIv1(index=1, base=0x40013000)
        self.spi2 = STM32SPIv1(index=2, base=0x40003800)
        self.add_peripheral(self.spi1)
        self.add_peripheral(self.spi2)

        self.i2c1 = STM32I2Cv2(index=1, base=0x40005400)
        self.i2c3 = STM32I2Cv2(index=3, base=0x40005C00)
        self.add_peripheral(self.i2c1)
        self.add_peripheral(self.i2c3)

    def _create_timers(self):
        """Create timer peripherals."""
        self.tim1 = STM32AdvancedTimer(index=1, base=0x40012C00)
        self.tim2 = STM32GeneralTimer(index=2, base=0x40000000, is_32bit=True)
        self.add_peripheral(self.tim1)
        self.add_peripheral(self.tim2)

        self.lptim1 = STM32LPTIM(index=1, base=0x40007C00)
        self.lptim2 = STM32LPTIM(index=2, base=0x40009400)
        self.add_peripheral(self.lptim1)
        self.add_peripheral(self.lptim2)

    def _create_analog(self):
        """Create ADC peripheral."""
        self.adc1 = STM32ADCv3(index=1, base=0x50040000)
        self.add_peripheral(self.adc1)

    def _create_dma(self):
        """Create DMA controllers."""
        self.dma1 = STM32DMAv1(index=1, base=0x40020000)
        self.dma2 = STM32DMAv1(index=2, base=0x40020400)
        self.add_peripheral(self.dma1)
        self.add_peripheral(self.dma2)

    def _create_security(self):
        """Create security peripherals."""
        self.aes1 = STM32AES(base=0x50060000)  # CPU1
        self.aes2 = STM32AES(base=0x58001800)  # CPU2/shared
        self.pka = STM32PKA(base=0x58002000)
        self.rng = STM32RNG(base=0x58001000, family="WB")

        self.add_peripheral(self.aes1)
        self.add_peripheral(self.aes2)
        self.add_peripheral(self.pka)
        self.add_peripheral(self.rng)

    def _create_multicore(self):
        """Create multi-core peripherals."""
        self.ipcc = STM32IPCC(base=0x58000C00)
        self.hsem = STM32HSEM(base=0x58001400)
        self.add_peripheral(self.ipcc)
        self.add_peripheral(self.hsem)

    def _create_misc(self):
        """Create miscellaneous peripherals."""
        self.syscfg = STM32SYSCFG(base=0x40010000, family="WB")
        self.iwdg = STM32IWDG(base=0x40003000)
        self.wwdg = STM32WWDG(base=0x40002C00, family="L4")
        self.rtc = STM32RTC(base=0x40002800, num_backup=20)
        self.crc = STM32CRC(base=0x40023000, family="L4")
        self.dbg = STM32DBG(base=0xE0042000, device="WB55")

        self.add_peripheral(self.syscfg)
        self.add_peripheral(self.iwdg)
        self.add_peripheral(self.wwdg)
        self.add_peripheral(self.rtc)
        self.add_peripheral(self.crc)
        self.add_peripheral(self.dbg)


class STM32WB55PeripheralSet(STM32WBxxPeripheralSet):
    """
    STM32WB55 peripheral set.

    Features:
    - Dual core: Cortex-M4 (64MHz) + Cortex-M0+ (32MHz)
    - BLE 5.0, IEEE 802.15.4, Thread, Zigbee
    - 1MB Flash, 256KB SRAM
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32WB55", log=log)


class STM32WB35PeripheralSet(STM32WBxxPeripheralSet):
    """
    STM32WB35 peripheral set (BLE only).

    Features:
    - Dual core: Cortex-M4 (64MHz) + Cortex-M0+ (32MHz)
    - BLE 5.0 only (no 802.15.4)
    - 512KB Flash, 96KB SRAM
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32WB35", log=log)
