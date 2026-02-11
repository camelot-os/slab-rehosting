/*
 * RP2040 Pico Dashboard Demo Firmware
 *
 * Bare-metal firmware that blinks the LED, sends UART messages,
 * and exercises GPIO pins for debug dashboard visualization.
 *
 * Peripherals used:
 * - SIO GPIO:  GP25 (LED), GP0, GP1, GP2
 * - UART0:     TX on GP0 (func 2)
 * - RESETS:    Release GPIO, UART from reset
 * - Delay:     Simple volatile loop (avoids TIMER MMIO overhead)
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2026 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>

/* ============================================================================
 * Base Addresses (RP2040 Datasheet Section 2.2)
 * ============================================================================ */
#define RESETS_BASE      0x4000C000UL
#define IO_BANK0_BASE    0x40014000UL
#define PADS_BANK0_BASE  0x4001C000UL
#define UART0_BASE       0x40034000UL

/* SIO uses a different address range (single-cycle I/O) */
#define SIO_BASE         0xD0000000UL

/* ============================================================================
 * RESETS
 * ============================================================================ */
#define RESETS_RESET       (*(volatile uint32_t *)(RESETS_BASE + 0x00))
#define RESETS_RESET_DONE  (*(volatile uint32_t *)(RESETS_BASE + 0x08))

/* Atomic SET/CLR aliases */
#define RESETS_RESET_CLR   (*(volatile uint32_t *)(RESETS_BASE + 0x3000 + 0x00))

#define RESETS_IO_BANK0    (1UL << 5)
#define RESETS_PADS_BANK0  (1UL << 8)
#define RESETS_UART0       (1UL << 22)

/* ============================================================================
 * SIO - Single-cycle I/O (GPIO fast access)
 * ============================================================================ */
#define SIO_GPIO_OUT       (*(volatile uint32_t *)(SIO_BASE + 0x10))
#define SIO_GPIO_OUT_SET   (*(volatile uint32_t *)(SIO_BASE + 0x14))
#define SIO_GPIO_OUT_CLR   (*(volatile uint32_t *)(SIO_BASE + 0x18))
#define SIO_GPIO_OUT_XOR   (*(volatile uint32_t *)(SIO_BASE + 0x1C))
#define SIO_GPIO_OE        (*(volatile uint32_t *)(SIO_BASE + 0x20))
#define SIO_GPIO_OE_SET    (*(volatile uint32_t *)(SIO_BASE + 0x24))

/* ============================================================================
 * IO_BANK0 - GPIO Function Select
 * ============================================================================ */
#define IO_BANK0_GPIO_CTRL(n) (*(volatile uint32_t *)(IO_BANK0_BASE + 0x04 + (n) * 8))

#define GPIO_FUNC_SIO   5
#define GPIO_FUNC_UART  2

/* ============================================================================
 * PADS_BANK0 - Pad Control
 * ============================================================================ */
#define PADS_BANK0_GPIO(n) (*(volatile uint32_t *)(PADS_BANK0_BASE + 0x04 + (n) * 4))

#define PADS_OD   (1UL << 7)  /* Output disable */
#define PADS_IE   (1UL << 6)  /* Input enable */
#define PADS_PUE  (1UL << 3)  /* Pull-up enable */
#define PADS_PDE  (1UL << 2)  /* Pull-down enable */

/* ============================================================================
 * UART0 - PL011 UART
 * ============================================================================ */
#define UART0_DR     (*(volatile uint32_t *)(UART0_BASE + 0x00))
#define UART0_FR     (*(volatile uint32_t *)(UART0_BASE + 0x18))
#define UART0_IBRD   (*(volatile uint32_t *)(UART0_BASE + 0x24))
#define UART0_FBRD   (*(volatile uint32_t *)(UART0_BASE + 0x28))
#define UART0_LCR_H  (*(volatile uint32_t *)(UART0_BASE + 0x2C))
#define UART0_CR     (*(volatile uint32_t *)(UART0_BASE + 0x30))

#define UART_FR_TXFF (1UL << 5)  /* TX FIFO full */
#define UART_FR_BUSY (1UL << 3)  /* UART busy */

#define UART_LCR_WLEN_8 (3UL << 5)  /* 8 data bits */
#define UART_LCR_FEN    (1UL << 4)  /* FIFO enable */

#define UART_CR_UARTEN (1UL << 0)
#define UART_CR_TXE    (1UL << 8)
#define UART_CR_RXE    (1UL << 9)

/* ============================================================================
 * Helper functions
 * ============================================================================ */

static void delay_ms(uint32_t ms)
{
    /*
     * Simple delay loop. In emulation, the CPU executes non-MMIO instructions
     * natively, so we need enough iterations to create visible timing gaps
     * in the dashboard logic analyzer. ~500K iterations ≈ 50ms at -O2.
     */
    volatile uint32_t count = ms * 500000;
    while (count--);
}

/* ============================================================================
 * UART functions
 * ============================================================================ */

static void uart_init(void)
{
    /* Release UART0 from reset */
    RESETS_RESET_CLR = RESETS_UART0;
    while (!(RESETS_RESET_DONE & RESETS_UART0));

    /* Disable UART for configuration */
    UART0_CR = 0;

    /* Set baud rate: 115200 @ 125MHz peri_clk
     * BAUDDIV = 125000000 / (16 * 115200) = 67.816...
     * IBRD = 67, FBRD = round(0.816 * 64) = 52 */
    UART0_IBRD = 67;
    UART0_FBRD = 52;

    /* 8N1, FIFO enabled */
    UART0_LCR_H = UART_LCR_WLEN_8 | UART_LCR_FEN;

    /* Enable UART, TX, RX */
    UART0_CR = UART_CR_UARTEN | UART_CR_TXE | UART_CR_RXE;

    /* Configure GP0 as UART0 TX (function 2) */
    IO_BANK0_GPIO_CTRL(0) = GPIO_FUNC_UART;
    PADS_BANK0_GPIO(0) = PADS_IE;  /* Enable output, input enable */
}

static void uart_putc(char c)
{
    /* Wait until TX FIFO not full */
    while (UART0_FR & UART_FR_TXFF);
    UART0_DR = c;
}

static void uart_puts(const char *s)
{
    while (*s) {
        if (*s == '\n') uart_putc('\r');
        uart_putc(*s++);
    }
}

static void uart_puthex8(uint8_t val)
{
    const char hex[] = "0123456789ABCDEF";
    uart_putc(hex[(val >> 4) & 0xF]);
    uart_putc(hex[val & 0xF]);
}

static void uart_puthex32(uint32_t val)
{
    for (int i = 28; i >= 0; i -= 4) {
        const char hex[] = "0123456789ABCDEF";
        uart_putc(hex[(val >> i) & 0xF]);
    }
}

static void uart_putdec(uint32_t val)
{
    char buf[12];
    int i = 0;
    if (val == 0) { uart_putc('0'); return; }
    while (val > 0) {
        buf[i++] = '0' + (val % 10);
        val /= 10;
    }
    while (i > 0) uart_putc(buf[--i]);
}

/* ============================================================================
 * GPIO functions
 * ============================================================================ */

static void gpio_init_output(uint32_t pin)
{
    IO_BANK0_GPIO_CTRL(pin) = GPIO_FUNC_SIO;
    PADS_BANK0_GPIO(pin) = PADS_IE;
    SIO_GPIO_OE_SET = (1UL << pin);
}

static void gpio_set(uint32_t pin)
{
    SIO_GPIO_OUT_SET = (1UL << pin);
}

static void gpio_clr(uint32_t pin)
{
    SIO_GPIO_OUT_CLR = (1UL << pin);
}

static void gpio_toggle(uint32_t pin)
{
    SIO_GPIO_OUT_XOR = (1UL << pin);
}

/* ============================================================================
 * Main application
 * ============================================================================ */

int main(void)
{
    /* Release IO_BANK0 + PADS from reset */
    RESETS_RESET_CLR = RESETS_IO_BANK0 | RESETS_PADS_BANK0;
    while (!(RESETS_RESET_DONE & (RESETS_IO_BANK0 | RESETS_PADS_BANK0)));

    /* Initialize UART0 */
    uart_init();

    /* Initialize GPIO outputs */
    gpio_init_output(25);  /* LED */
    gpio_init_output(1);   /* GP1 - activity indicator */
    gpio_init_output(2);   /* GP2 - heartbeat */

    /* Banner */
    uart_puts("\n");
    uart_puts("==============================\n");
    uart_puts(" Raspberry Pi Pico Dashboard\n");
    uart_puts(" RP2040 @ 125 MHz\n");
    uart_puts("==============================\n");
    uart_puts("[INIT] GPIO25 LED configured\n");
    uart_puts("[INIT] UART0 @ 115200 baud\n");
    uart_puts("[INIT] GP1, GP2 activity pins\n");
    uart_puts("\n");

    /* Main loop */
    uint32_t cycle = 0;
    while (1) {
        /* Toggle LED every iteration */
        gpio_toggle(25);

        /* GP1 follows LED (activity indicator) */
        if (cycle & 1) {
            gpio_set(1);
        } else {
            gpio_clr(1);
        }

        /* GP2 heartbeat: on for 1 cycle, off for 3 */
        if ((cycle & 3) == 0) {
            gpio_set(2);
        } else {
            gpio_clr(2);
        }

        /* Periodic UART output */
        if ((cycle % 4) == 0) {
            uart_puts("[");
            uart_putdec(cycle);
            uart_puts("] LED=");
            uart_puts((cycle & 1) ? "ON " : "OFF");
            uart_puts(" GP1=");
            uart_putc((cycle & 1) ? '1' : '0');
            uart_puts(" GP2=");
            uart_putc(((cycle & 3) == 0) ? '1' : '0');
            uart_puts("\n");
        }

        /* Status summary every 20 cycles */
        if (cycle > 0 && (cycle % 20) == 0) {
            uart_puts("--- ");
            uart_putdec(cycle);
            uart_puts(" cycles completed ---\n");
        }

        cycle++;

        /* Delay between iterations */
        delay_ms(200);

        /* Stop after 100 cycles to avoid infinite loop in emulation */
        if (cycle >= 100) {
            uart_puts("\n[DONE] 100 cycles completed\n");
            uart_puts("Dashboard demo finished.\n");
            break;
        }
    }

    /* Final state: LED off */
    gpio_clr(25);
    gpio_clr(1);
    gpio_clr(2);

    while (1) {
        /* Halt */
        __asm volatile("wfi");
    }

    return 0;
}

/* ============================================================================
 * Startup code
 * ============================================================================ */

void Reset_Handler(void)
{
    main();
    while (1);
}

void Default_Handler(void)
{
    while (1);
}

__attribute__((section(".vectors")))
void (* const vectors[])(void) = {
    (void (*)(void))0x20040000,  /* Initial SP (top of 256KB SRAM) */
    Reset_Handler,               /* Reset */
    Default_Handler,             /* NMI */
    Default_Handler,             /* HardFault */
    Default_Handler,             /* MemManage */
    Default_Handler,             /* BusFault */
    Default_Handler,             /* UsageFault */
    0, 0, 0, 0,                 /* Reserved */
    Default_Handler,             /* SVCall */
    Default_Handler,             /* Debug */
    0,                           /* Reserved */
    Default_Handler,             /* PendSV */
    Default_Handler,             /* SysTick */
};
