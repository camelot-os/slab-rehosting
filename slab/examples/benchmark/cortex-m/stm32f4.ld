/*
 * SLAB Benchmark Linker Script
 * Target: STM32F4 (or compatible memory map)
 */

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 512K
    SRAM (rwx)  : ORIGIN = 0x20000000, LENGTH = 128K
}

ENTRY(main)

SECTIONS
{
    /* Vector table at start of flash */
    .vectors :
    {
        . = ALIGN(4);
        KEEP(*(.vectors))
        . = ALIGN(4);
    } > FLASH

    /* Code */
    .text :
    {
        . = ALIGN(4);
        *(.text)
        *(.text*)
        *(.rodata)
        *(.rodata*)
        . = ALIGN(4);
        _etext = .;
    } > FLASH

    /* Initialized data */
    .data :
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data)
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } > SRAM AT > FLASH

    _sidata = LOADADDR(.data);

    /* Uninitialized data */
    .bss :
    {
        . = ALIGN(4);
        _sbss = .;
        *(.bss)
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > SRAM

    /* Stack */
    .stack (NOLOAD) :
    {
        . = ALIGN(8);
        _sstack = .;
        . = . + 0x1000;  /* 4KB stack */
        _estack = .;
    } > SRAM

    /* Discard */
    /DISCARD/ :
    {
        *(.ARM.attributes)
        *(.ARM.exidx*)
        *(.eh_frame)
    }
}

/* Provide default values */
PROVIDE(_stack_top = ORIGIN(SRAM) + LENGTH(SRAM));
