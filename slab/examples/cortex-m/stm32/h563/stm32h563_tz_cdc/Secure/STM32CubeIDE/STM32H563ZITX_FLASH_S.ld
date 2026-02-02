/**
 * Linker script for STM32H563ZI - Secure world
 *
 * Memory regions:
 *   Secure Flash:  0x0C000000 - 0x0C03FFFF (256KB)
 *   NSC Flash:     0x0C040000 - 0x0C041FFF (8KB)
 *   Secure SRAM1:  0x30000000 - 0x3001FFFF (128KB)
 */

/* Entry Point */
ENTRY(Reset_Handler)

/* Highest address of the stack */
_estack = ORIGIN(RAM) + LENGTH(RAM);

/* Minimum heap and stack sizes */
_Min_Heap_Size = 0x400;   /* 1KB */
_Min_Stack_Size = 0x800;  /* 2KB */

MEMORY
{
    FLASH_S   (rx)  : ORIGIN = 0x0C000000, LENGTH = 256K
    FLASH_NSC (rx)  : ORIGIN = 0x0C040000, LENGTH = 8K
    RAM_S     (rwx) : ORIGIN = 0x30000000, LENGTH = 128K
}

/* Alias for stack placement */
REGION_ALIAS("RAM", RAM_S);

SECTIONS
{
    /* Interrupt vector table */
    .isr_vector :
    {
        . = ALIGN(4);
        KEEP(*(.isr_vector))
        . = ALIGN(4);
    } >FLASH_S

    /* Program code */
    .text :
    {
        . = ALIGN(4);
        *(.text)
        *(.text*)
        *(.glue_7)
        *(.glue_7t)
        *(.eh_frame)

        KEEP(*(.init))
        KEEP(*(.fini))

        . = ALIGN(4);
        _etext = .;
    } >FLASH_S

    /* Read-only data */
    .rodata :
    {
        . = ALIGN(4);
        *(.rodata)
        *(.rodata*)
        . = ALIGN(4);
    } >FLASH_S

    /* ARM exception handling */
    .ARM.extab :
    {
        *(.ARM.extab* .gnu.linkonce.armextab.*)
    } >FLASH_S

    .ARM :
    {
        __exidx_start = .;
        *(.ARM.exidx*)
        __exidx_end = .;
    } >FLASH_S

    /* Constructors */
    .preinit_array :
    {
        PROVIDE_HIDDEN(__preinit_array_start = .);
        KEEP(*(.preinit_array*))
        PROVIDE_HIDDEN(__preinit_array_end = .);
    } >FLASH_S

    .init_array :
    {
        PROVIDE_HIDDEN(__init_array_start = .);
        KEEP(*(SORT(.init_array.*)))
        KEEP(*(.init_array*))
        PROVIDE_HIDDEN(__init_array_end = .);
    } >FLASH_S

    .fini_array :
    {
        PROVIDE_HIDDEN(__fini_array_start = .);
        KEEP(*(SORT(.fini_array.*)))
        KEEP(*(.fini_array*))
        PROVIDE_HIDDEN(__fini_array_end = .);
    } >FLASH_S

    /* Non-Secure Callable (NSC) veneer region */
    .gnu.sgstubs :
    {
        . = ALIGN(32);
        *(.gnu.sgstubs*)
        . = ALIGN(32);
    } >FLASH_NSC

    /* Used by startup to initialize data */
    _sidata = LOADADDR(.data);

    /* Initialized data */
    .data :
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data)
        *(.data*)
        /* GOT sections must be included for PIC/PIE code to work */
        *(.got)
        *(.got.plt)
        . = ALIGN(4);
        _edata = .;
    } >RAM_S AT> FLASH_S

    /* Uninitialized data (BSS) */
    .bss :
    {
        . = ALIGN(4);
        _sbss = .;
        __bss_start__ = _sbss;
        *(.bss)
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
        __bss_end__ = _ebss;
    } >RAM_S

    /* User heap */
    ._user_heap_stack :
    {
        . = ALIGN(8);
        PROVIDE(end = .);
        PROVIDE(_end = .);
        . = . + _Min_Heap_Size;
        . = . + _Min_Stack_Size;
        . = ALIGN(8);
    } >RAM_S

    /* Discard unused sections */
    /DISCARD/ :
    {
        libc.a(*)
        libm.a(*)
        libgcc.a(*)
    }

    .ARM.attributes 0 : { *(.ARM.attributes) }
}
