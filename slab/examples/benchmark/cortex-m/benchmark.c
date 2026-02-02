/**
 * SLAB Benchmark Firmware
 *
 * Standardized benchmark for comparing emulation frameworks.
 * Target: Cortex-M4 (STM32F4 compatible memory map)
 *
 * Benchmark phases:
 *   1. CPU baseline (no MMIO)
 *   2. GPIO read/write
 *   3. SPI transactions
 *   4. Mixed workload
 *
 * Results are reported via semihosting or magic address.
 */

#include <stdint.h>

/* Memory map (STM32F4 compatible) */
#define FLASH_BASE      0x08000000
#define SRAM_BASE       0x20000000
#define PERIPH_BASE     0x40000000

/* Peripheral addresses */
#define RCC_BASE        (PERIPH_BASE + 0x00023800)
#define GPIOA_BASE      (PERIPH_BASE + 0x00020000)
#define GPIOB_BASE      (PERIPH_BASE + 0x00020400)
#define SPI1_BASE       (PERIPH_BASE + 0x00013000)
#define USART1_BASE     (PERIPH_BASE + 0x00011000)

/* GPIO registers */
#define GPIO_MODER(base)    (*(volatile uint32_t*)((base) + 0x00))
#define GPIO_OTYPER(base)   (*(volatile uint32_t*)((base) + 0x04))
#define GPIO_OSPEEDR(base)  (*(volatile uint32_t*)((base) + 0x08))
#define GPIO_PUPDR(base)    (*(volatile uint32_t*)((base) + 0x0C))
#define GPIO_IDR(base)      (*(volatile uint32_t*)((base) + 0x10))
#define GPIO_ODR(base)      (*(volatile uint32_t*)((base) + 0x14))
#define GPIO_BSRR(base)     (*(volatile uint32_t*)((base) + 0x18))

/* SPI registers */
#define SPI_CR1(base)       (*(volatile uint32_t*)((base) + 0x00))
#define SPI_CR2(base)       (*(volatile uint32_t*)((base) + 0x04))
#define SPI_SR(base)        (*(volatile uint32_t*)((base) + 0x08))
#define SPI_DR(base)        (*(volatile uint32_t*)((base) + 0x0C))

/* RCC registers */
#define RCC_CR          (*(volatile uint32_t*)(RCC_BASE + 0x00))
#define RCC_AHB1ENR     (*(volatile uint32_t*)(RCC_BASE + 0x30))
#define RCC_APB2ENR     (*(volatile uint32_t*)(RCC_BASE + 0x44))

/* Benchmark magic addresses for result reporting
 * Must be in SLAB proxy region: 0x40000000-0x5FFFFFFF
 * Using 0x50000000 area (high periph region, unlikely to conflict)
 */
#define BENCH_START     (*(volatile uint32_t*)0x50000000)
#define BENCH_END       (*(volatile uint32_t*)0x50000004)
#define BENCH_RESULT    (*(volatile uint32_t*)0x50000008)
#define BENCH_PHASE     (*(volatile uint32_t*)0x5000000C)

/* Benchmark configuration */
#define CPU_ITERATIONS      1000000
#define GPIO_ITERATIONS     100000
#define SPI_ITERATIONS      10000
#define MIXED_ITERATIONS    50000

/* Phase identifiers */
#define PHASE_INIT      0
#define PHASE_CPU       1
#define PHASE_GPIO      2
#define PHASE_SPI       3
#define PHASE_MIXED     4
#define PHASE_DONE      0xFF

/**
 * Prevent compiler optimization of benchmark loops
 */
static volatile uint32_t sink;

/**
 * Signal benchmark phase start
 */
static inline void bench_start(uint32_t phase) {
    BENCH_PHASE = phase;
    BENCH_START = 1;
}

/**
 * Signal benchmark phase end with result
 */
static inline void bench_end(uint32_t result) {
    BENCH_RESULT = result;
    BENCH_END = 1;
}

/**
 * Phase 1: CPU baseline
 * Pure computation, no MMIO access
 */
static uint32_t benchmark_cpu(void) {
    volatile uint32_t counter = 0;
    volatile uint32_t acc = 0;

    bench_start(PHASE_CPU);

    for (uint32_t i = 0; i < CPU_ITERATIONS; i++) {
        acc += i;
        acc ^= (acc << 3);
        acc += (acc >> 5);
        counter++;
    }

    bench_end(counter);
    sink = acc;  /* Prevent dead code elimination */

    return counter;
}

/**
 * Phase 2: GPIO benchmark
 * Read and write GPIO registers
 */
static uint32_t benchmark_gpio(void) {
    volatile uint32_t counter = 0;
    uint32_t val;

    /* Enable GPIOA clock */
    RCC_AHB1ENR |= (1 << 0);

    /* Configure GPIOA as output */
    GPIO_MODER(GPIOA_BASE) = 0x55555555;  /* All outputs */

    bench_start(PHASE_GPIO);

    for (uint32_t i = 0; i < GPIO_ITERATIONS; i++) {
        /* Write pattern */
        GPIO_ODR(GPIOA_BASE) = i & 0xFFFF;

        /* Read back */
        val = GPIO_IDR(GPIOA_BASE);

        /* Atomic bit set/reset */
        GPIO_BSRR(GPIOA_BASE) = 0x00010001;  /* Set bit 0, reset bit 16 */

        counter++;
    }

    bench_end(counter);
    sink = val;

    return counter;
}

/**
 * Phase 3: SPI benchmark
 * Simulated SPI transactions
 */
static uint32_t benchmark_spi(void) {
    volatile uint32_t counter = 0;
    uint32_t rx_data;

    /* Enable SPI1 clock */
    RCC_APB2ENR |= (1 << 12);

    /* Configure SPI (basic settings) */
    SPI_CR1(SPI1_BASE) = (1 << 2) |    /* Master mode */
                         (3 << 3) |    /* Baud rate /16 */
                         (1 << 6);     /* SPI enable */

    bench_start(PHASE_SPI);

    for (uint32_t i = 0; i < SPI_ITERATIONS; i++) {
        /* 8-byte transaction */
        for (int j = 0; j < 8; j++) {
            /* Wait for TXE */
            while (!(SPI_SR(SPI1_BASE) & (1 << 1)));

            /* Write data */
            SPI_DR(SPI1_BASE) = (i + j) & 0xFF;

            /* Wait for RXNE */
            while (!(SPI_SR(SPI1_BASE) & (1 << 0)));

            /* Read data */
            rx_data = SPI_DR(SPI1_BASE);
        }

        counter++;
    }

    bench_end(counter);
    sink = rx_data;

    return counter;
}

/**
 * Phase 4: Mixed workload
 * Combination of CPU, GPIO, and memory operations
 */
static uint32_t benchmark_mixed(void) {
    volatile uint32_t counter = 0;
    uint32_t acc = 0;
    uint32_t gpio_val;

    bench_start(PHASE_MIXED);

    for (uint32_t i = 0; i < MIXED_ITERATIONS; i++) {
        /* CPU work */
        acc += i;
        acc ^= (acc << 3);

        /* GPIO toggle */
        GPIO_ODR(GPIOA_BASE) = acc & 0xFFFF;
        gpio_val = GPIO_IDR(GPIOA_BASE);

        /* More CPU work */
        acc += gpio_val;
        acc ^= (acc >> 5);

        /* Memory access (SRAM) */
        *(volatile uint32_t*)(SRAM_BASE + (i & 0xFFF)) = acc;

        counter++;
    }

    bench_end(counter);
    sink = acc;

    return counter;
}

/**
 * Initialize system
 */
static void system_init(void) {
    /* Basic RCC setup - enable HSI */
    RCC_CR |= (1 << 0);  /* HSI ON */

    /* Wait for HSI ready (or timeout in emulation) */
    for (volatile int i = 0; i < 1000; i++) {
        if (RCC_CR & (1 << 1)) break;  /* HSI RDY */
    }

    bench_start(PHASE_INIT);
    bench_end(1);
}

/**
 * Main entry point
 */
int main(void) {
    uint32_t results[4];

    system_init();

    /* Run all benchmarks */
    results[0] = benchmark_cpu();
    results[1] = benchmark_gpio();
    results[2] = benchmark_spi();
    results[3] = benchmark_mixed();

    /* Signal completion */
    BENCH_PHASE = PHASE_DONE;
    BENCH_RESULT = results[0] + results[1] + results[2] + results[3];
    BENCH_END = 1;

    /* Infinite loop */
    while (1) {
        __asm__("wfi");
    }

    return 0;
}

/* Vector table */
__attribute__((section(".vectors")))
const void* vectors[] = {
    (void*)0x20010000,  /* Initial SP */
    (void*)main,        /* Reset handler */
    /* ... other vectors would go here */
};
