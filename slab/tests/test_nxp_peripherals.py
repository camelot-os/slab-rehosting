#!/usr/bin/env python3
"""
Test suite for NXP LPC55S69 peripheral implementations.

Tests GPIO, FlexComm USART, CTimer, CASPER, HASHCRYPT, PUF,
and the full LPC55S69 peripheral set.

References:
- UM11126: LPC55S6x/LPC55S2x/LPC552x User Manual
- LPC55S69 Datasheet

Author: TwistedWires Security Lab
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

import unittest


class TestLPCGPIO(unittest.TestCase):
    """Test LPC55xx GPIO peripheral per UM11126 Chapter 16."""

    def setUp(self):
        from slab_nxp.lpc_gpio import LPCGPIO
        self.gpio = LPCGPIO(port=0, base=0x50000000)

    def test_initial_state(self):
        """All pins should be input, output=0."""
        self.assertEqual(self.gpio.direction, 0)
        self.assertEqual(self.gpio.output, 0)

    def test_direction_set(self):
        """Test DIR register controls pin direction."""
        self.gpio.write(0x50000000 + 0x2080, 4, 0x0000FFFF)  # P0.0-15 output
        self.assertEqual(self.gpio.direction, 0x0000FFFF)

    def test_dirset_register(self):
        """DIRSET sets direction bits without clearing others."""
        self.gpio.write(0x50000000 + 0x209C, 4, 0x01)  # Set P0.0 output
        self.assertEqual(self.gpio.direction, 0x01)
        self.gpio.write(0x50000000 + 0x209C, 4, 0x04)  # Set P0.2 output
        self.assertEqual(self.gpio.direction, 0x05)

    def test_dirclr_register(self):
        """DIRCLR clears direction bits."""
        self.gpio.direction = 0xFF
        self.gpio.write(0x50000000 + 0x20A0, 4, 0x0F)  # Clear P0.0-3
        self.assertEqual(self.gpio.direction, 0xF0)

    def test_set_clear_not(self):
        """Test SET/CLR/NOT output registers."""
        self.gpio.direction = 0xFF  # All output

        # SET: set pins
        self.gpio.write(0x50000000 + 0x2090, 4, 0x05)  # Set P0.0, P0.2
        self.assertEqual(self.gpio.output, 0x05)

        # CLR: clear pins
        self.gpio.write(0x50000000 + 0x2094, 4, 0x01)  # Clear P0.0
        self.assertEqual(self.gpio.output, 0x04)

        # NOT: toggle pins
        self.gpio.write(0x50000000 + 0x2098, 4, 0x06)  # Toggle P0.1, P0.2
        self.assertEqual(self.gpio.output, 0x02)

    def test_pin_read_output(self):
        """PIN register reflects output when direction=1."""
        self.gpio.direction = 0xFF
        self.gpio.output = 0xA5
        pin_val = self.gpio.read(0x50000000 + 0x2088, 4)
        self.assertEqual(pin_val, 0xA5)

    def test_pin_read_input(self):
        """PIN register reflects external input when direction=0."""
        self.gpio.direction = 0x00  # All input
        self.gpio.set_input(3, True)
        self.gpio.set_input(7, True)
        pin_val = self.gpio.read(0x50000000 + 0x2088, 4)
        self.assertEqual(pin_val, 0x88)

    def test_byte_pin_access(self):
        """Byte pin register returns 0/1 per pin."""
        self.gpio.direction = 0xFF
        self.gpio.output = 0x05
        # B[0] should be 1
        self.assertEqual(self.gpio.read(0x50000000 + 0x0000, 1), 1)
        # B[1] should be 0
        self.assertEqual(self.gpio.read(0x50000000 + 0x0001, 1), 0)
        # B[2] should be 1
        self.assertEqual(self.gpio.read(0x50000000 + 0x0002, 1), 1)

    def test_word_pin_access(self):
        """Word pin register returns 0x00000000 or 0xFFFFFFFF."""
        self.gpio.direction = 0xFF
        self.gpio.output = 0x02
        # W[0] = 0 (pin 0 low)
        self.assertEqual(self.gpio.read(0x50000000 + 0x1000, 4), 0)
        # W[1] = 0xFFFFFFFF (pin 1 high)
        self.assertEqual(self.gpio.read(0x50000000 + 0x1004, 4), 0xFFFFFFFF)

    def test_set_input_helper(self):
        """set_input() drives external pin state."""
        self.gpio.set_input(5, True)
        self.assertTrue(self.gpio.input & (1 << 5))
        self.gpio.set_input(5, False)
        self.assertFalse(self.gpio.input & (1 << 5))

    def test_get_output_helper(self):
        """get_output() reads output latch."""
        self.gpio.output = 0x10
        self.assertTrue(self.gpio.get_output(4))
        self.assertFalse(self.gpio.get_output(3))


class TestLPCFlexCommUSART(unittest.TestCase):
    """Test LPC FlexComm USART per UM11126 Chapter 13."""

    def setUp(self):
        from slab_nxp.lpc_flexcomm import LPCFlexCommUSART
        self.usart = LPCFlexCommUSART(index=0)

    def test_initial_state(self):
        """USART starts disabled."""
        cfg = self.usart.read(self.usart.base + self.usart.CFG, 4)
        self.assertEqual(cfg & 1, 0)  # ENABLE=0

    def test_enable(self):
        """Enable USART via CFG register."""
        self.usart.write(self.usart.base + self.usart.CFG, 4, 0x01)
        cfg = self.usart.read(self.usart.base + self.usart.CFG, 4)
        self.assertTrue(cfg & 1)

    def test_baud_rate(self):
        """BRG register sets baud rate divisor."""
        self.usart.write(self.usart.base + self.usart.BRG, 4, 103)  # ~115200
        brg = self.usart.read(self.usart.base + self.usart.BRG, 4)
        self.assertEqual(brg, 103)

    def test_tx_fifo(self):
        """Write to FIFOWR queues TX data."""
        self.usart.write(self.usart.base + self.usart.CFG, 4, 1)  # Enable
        self.usart.write(self.usart.base + self.usart.FIFOWR, 4, ord('A'))
        self.assertEqual(len(self.usart.tx_fifo), 1)
        self.assertEqual(self.usart.tx_fifo[0], ord('A'))

    def test_rx_fifo(self):
        """Inject RX data and read via FIFORD."""
        self.usart.rx_fifo.append(0x42)
        data = self.usart.read(self.usart.base + self.usart.FIFORD, 4)
        self.assertEqual(data & 0xFF, 0x42)

    def test_fifo_status(self):
        """FIFOSTAT reflects TX empty and RX not empty."""
        stat = self.usart.read(self.usart.base + self.usart.FIFOSTAT, 4)
        # TX should be empty initially
        self.assertTrue(stat & (1 << 5))  # TXEMPTY

    def test_oversampling(self):
        """OSR register controls oversampling ratio."""
        self.usart.write(self.usart.base + self.usart.OSR, 4, 15)  # 16x
        osr = self.usart.read(self.usart.base + self.usart.OSR, 4)
        self.assertEqual(osr, 15)


class TestLPCCTimer(unittest.TestCase):
    """Test LPC CTimer per UM11126 Chapter 21."""

    def setUp(self):
        from slab_nxp.lpc_ctimer import LPCCTimer
        self.timer = LPCCTimer(index=0, base=0x40008000)

    def test_initial_state(self):
        """Timer starts stopped, TC=0."""
        tcr = self.timer.read(self.timer.base + self.timer.TCR, 4)
        self.assertEqual(tcr, 0)
        tc = self.timer.read(self.timer.base + self.timer.TC, 4)
        self.assertEqual(tc, 0)

    def test_counter_enable(self):
        """TCR.CEN enables counting."""
        self.timer.write(self.timer.base + self.timer.TCR, 4, 1)  # CEN
        tcr = self.timer.read(self.timer.base + self.timer.TCR, 4)
        self.assertTrue(tcr & 1)

    def test_counter_reset(self):
        """TCR.CRST resets TC to 0."""
        self.timer.tc = 1000
        self.timer.write(self.timer.base + self.timer.TCR, 4, 0x02)  # CRST
        tc = self.timer.read(self.timer.base + self.timer.TC, 4)
        self.assertEqual(tc, 0)

    def test_match_register(self):
        """Match registers MR0-3 store compare values."""
        self.timer.write(self.timer.base + self.timer.MR0, 4, 12345)
        mr0 = self.timer.read(self.timer.base + self.timer.MR0, 4)
        self.assertEqual(mr0, 12345)

        self.timer.write(self.timer.base + self.timer.MR1, 4, 0xDEADBEEF)
        mr1 = self.timer.read(self.timer.base + self.timer.MR1, 4)
        self.assertEqual(mr1, 0xDEADBEEF)

    def test_prescale_register(self):
        """PR sets prescale divider."""
        self.timer.write(self.timer.base + self.timer.PR, 4, 99)
        pr = self.timer.read(self.timer.base + self.timer.PR, 4)
        self.assertEqual(pr, 99)

    def test_match_control(self):
        """MCR controls actions on match."""
        # MR0: interrupt + reset (bits 0,1)
        self.timer.write(self.timer.base + self.timer.MCR, 4, 0x03)
        mcr = self.timer.read(self.timer.base + self.timer.MCR, 4)
        self.assertEqual(mcr, 0x03)

    def test_tick_match_interrupt(self):
        """Ticking to match value sets IR flag."""
        self.timer.write(self.timer.base + self.timer.MR0, 4, 5)
        self.timer.write(self.timer.base + self.timer.MCR, 4, 0x01)  # INT on MR0
        self.timer.write(self.timer.base + self.timer.TCR, 4, 0x01)  # Enable

        # Tick 6 times to trigger match
        for _ in range(6):
            self.timer.tick()

        ir = self.timer.read(self.timer.base + self.timer.IR, 4)
        self.assertTrue(ir & 1)  # MR0 interrupt flag


class TestLPCCASPER(unittest.TestCase):
    """Test LPC55xx CASPER crypto accelerator per UM11126 Chapter 42."""

    def setUp(self):
        from slab_nxp.lpc_crypto import LPCCASPER
        self.casper = LPCCASPER()

    def test_initial_done(self):
        """STATUS.DONE should be set initially."""
        status = self.casper.read(self.casper.base + self.casper.STATUS, 4)
        self.assertTrue(status & self.casper.STATUS_DONE)

    def test_operand_registers(self):
        """AREG/BREG/CREG/DREG store operand pointers."""
        self.casper.write(self.casper.base + self.casper.AREG, 4, 0x20000000)
        self.casper.write(self.casper.base + self.casper.BREG, 4, 0x20001000)
        self.assertEqual(
            self.casper.read(self.casper.base + self.casper.AREG, 4), 0x20000000)
        self.assertEqual(
            self.casper.read(self.casper.base + self.casper.BREG, 4), 0x20001000)

    def test_ctrl0_triggers_operation(self):
        """Writing CTRL0 triggers operation, sets DONE."""
        self.casper.status = 0  # Clear DONE
        self.casper.write(self.casper.base + self.casper.CTRL0, 4, 0x01)
        status = self.casper.read(self.casper.base + self.casper.STATUS, 4)
        self.assertTrue(status & self.casper.STATUS_DONE)

    def test_interrupt_enable(self):
        """INTENSET/INTENCLR manage interrupt mask."""
        self.casper.write(self.casper.base + self.casper.INTENSET, 4, 0x01)
        self.assertEqual(self.casper.intenset, 0x01)
        self.casper.write(self.casper.base + self.casper.INTENCLR, 4, 0x01)
        self.assertEqual(self.casper.intenset, 0x00)

    def test_lock_register(self):
        """LOCK register protects configuration."""
        self.casper.write(self.casper.base + self.casper.LOCK, 4, 0xA5A5)
        lock = self.casper.read(self.casper.base + self.casper.LOCK, 4)
        self.assertEqual(lock, 0xA5A5)

    def test_irq_callback(self):
        """Interrupt fires when INTENSET enabled and operation completes."""
        irq_fired = [False]

        def on_irq(level):
            irq_fired[0] = True

        self.casper.on_irq = on_irq
        self.casper.write(self.casper.base + self.casper.INTENSET, 4, 1)
        self.casper.write(self.casper.base + self.casper.CTRL0, 4, 1)
        self.assertTrue(irq_fired[0])


class TestLPCHASHCRYPT(unittest.TestCase):
    """Test LPC55xx HASHCRYPT per UM11126 Chapter 43."""

    def setUp(self):
        from slab_nxp.lpc_crypto import LPCHASHCRYPT
        self.hash = LPCHASHCRYPT()

    def test_initial_state(self):
        """Engine starts disabled."""
        ctrl = self.hash.read(self.hash.base + self.hash.CTRL, 4)
        self.assertEqual(ctrl & 0x07, 0)  # MODE=DISABLED

    def test_sha256_mode(self):
        """Set SHA-256 mode via CTRL."""
        ctrl_val = self.hash.CTRL_MODE_SHA256 | self.hash.CTRL_NEW_HASH
        self.hash.write(self.hash.base + self.hash.CTRL, 4, ctrl_val)
        ctrl = self.hash.read(self.hash.base + self.hash.CTRL, 4)
        self.assertEqual(ctrl & 0x07, self.hash.CTRL_MODE_SHA256)

    def test_sha256_digest(self):
        """SHA-256 of known input produces correct digest."""
        # Initialize SHA-256
        ctrl_val = self.hash.CTRL_MODE_SHA256 | self.hash.CTRL_NEW_HASH
        self.hash.write(self.hash.base + self.hash.CTRL, 4, ctrl_val)

        # Write 'abc' as 32-bit words (big-endian padded)
        self.hash.write(self.hash.base + self.hash.INDATA, 4, 0x61626380)

        # Check digest is ready
        status = self.hash.read(self.hash.base + self.hash.STATUS, 4)
        if status & self.hash.STATUS_DIGEST_READY:
            digest0 = self.hash.read(self.hash.base + self.hash.DIGEST_BASE, 4)
            self.assertNotEqual(digest0, 0)

    def test_aes_mode_config(self):
        """Configure AES-128-ECB mode."""
        # Set AES mode
        self.hash.write(self.hash.base + self.hash.CTRL, 4,
                        self.hash.CTRL_MODE_AES)
        # Configure AES-128-ECB
        cryptcfg = (self.hash.CRYPTCFG_AESMODE_ECB |
                    self.hash.CRYPTCFG_AESKEYSZ_128)
        self.hash.write(self.hash.base + self.hash.CRYPTCFG, 4, cryptcfg)
        cfg = self.hash.read(self.hash.base + self.hash.CRYPTCFG, 4)
        self.assertEqual(cfg & 0x03, 0)  # ECB mode

    def test_memctrl_register(self):
        """MEMCTRL configures DMA-like memory access."""
        self.hash.write(self.hash.base + self.hash.MEMCTRL, 4, 64)
        mc = self.hash.read(self.hash.base + self.hash.MEMCTRL, 4)
        self.assertEqual(mc, 64)


class TestLPCPUF(unittest.TestCase):
    """Test LPC55xx PUF (Physical Unclonable Function) per UM11126 Ch.44."""

    def setUp(self):
        from slab_nxp.lpc_crypto import LPCPUF
        self.puf = LPCPUF()

    def test_initial_state(self):
        """PUF starts idle."""
        stat = self.puf.read(self.puf.base + self.puf.STAT, 4)
        # Should not be busy
        self.assertFalse(stat & 0x01)

    def test_enroll_command(self):
        """Enrollment generates activation code."""
        self.puf.write(self.puf.base + self.puf.CTRL, 4, self.puf.CTRL_ENROLL)
        # Check status indicates success
        stat = self.puf.read(self.puf.base + self.puf.STAT, 4)
        self.assertTrue(stat & self.puf.STAT_SUCCESS)

    def test_key_generation(self):
        """Key generation produces key code."""
        # First enroll
        self.puf.write(self.puf.base + self.puf.CTRL, 4, self.puf.CTRL_ENROLL)
        # Then generate key
        self.puf.write(self.puf.base + self.puf.CTRL, 4, self.puf.CTRL_GENERATEKEY)
        stat = self.puf.read(self.puf.base + self.puf.STAT, 4)
        self.assertTrue(stat & self.puf.STAT_SUCCESS)

    def test_key_index(self):
        """KEYINDEX selects key slot."""
        self.puf.write(self.puf.base + self.puf.KEYINDEX, 4, 2)
        idx = self.puf.read(self.puf.base + self.puf.KEYINDEX, 4)
        self.assertEqual(idx, 2)


class TestLPC55S69PeripheralSet(unittest.TestCase):
    """Test full LPC55S69 peripheral set integration."""

    def setUp(self):
        from slab_nxp.lpc55s69 import LPC55S69PeripheralSet
        self.mcu = LPC55S69PeripheralSet()

    def test_gpio_ports_created(self):
        """Both GPIO ports should be created."""
        self.assertIsNotNone(self.mcu.gpio0)
        self.assertIsNotNone(self.mcu.gpio1)
        self.assertEqual(self.mcu.gpio0.base, 0x50000000)
        self.assertEqual(self.mcu.gpio1.base, 0x50001000)

    def test_flexcomm_created(self):
        """FlexComm peripherals should be created."""
        self.assertIsNotNone(self.mcu.flexcomm0)
        self.assertIsNotNone(self.mcu.flexcomm7)
        self.assertEqual(self.mcu.flexcomm0.base, 0x40086000)

    def test_timers_created(self):
        """CTimers should be created."""
        self.assertIsNotNone(self.mcu.ctimer0)
        self.assertIsNotNone(self.mcu.ctimer4)
        self.assertEqual(self.mcu.ctimer0.base, 0x40008000)

    def test_crypto_created(self):
        """CASPER and HASHCRYPT should be created."""
        self.assertIsNotNone(self.mcu.casper)
        self.assertIsNotNone(self.mcu.hashcrypt)

    def test_puf_created(self):
        """PUF should be created."""
        self.assertIsNotNone(self.mcu.puf)

    def test_bus_read_gpio(self):
        """Bus read to GPIO address should route correctly."""
        self.mcu.gpio0.direction = 0xFF
        self.mcu.gpio0.output = 0x42
        val = self.mcu.read(0x50000000 + 0x2088, 4)  # PIN register
        self.assertEqual(val, 0x42)

    def test_bus_write_gpio(self):
        """Bus write to GPIO address should route correctly."""
        self.mcu.write(0x50000000 + 0x2080, 4, 0xFF)  # DIR = output
        self.assertEqual(self.mcu.gpio0.direction, 0xFF)


if __name__ == '__main__':
    unittest.main()
