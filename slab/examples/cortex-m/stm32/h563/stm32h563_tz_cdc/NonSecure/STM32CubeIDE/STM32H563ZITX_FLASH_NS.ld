/**
 * Linker script for STM32H563ZI - Non-Secure world
 *
 * Memory regions:
 *   Non-Secure Flash: 0x08042000 - 0x081FFFFF (~1.75MB)
 *   Non-Secure SRAM:  0x20020000 - 0x2009FFFF (512KB)
 */

/* Entry Point */
ENTRY(Reset_Handler)

/* Highest address of the stack */
_estack = ORIGIN(RAM) + LENGTH(RAM);

/* Minimum heap and stack sizes */
_Min_Heap_Size = 0x2000;   /* 8KB (for USBX/ThreadX) */
_Min_Stack_Size = 0x1000;  /* 4KB */

MEMORY
{
    FLASH_NS  (rx)  : ORIGIN = 0x08042000, LENGTH = 1784K
    RAM_NS    (rwx) : ORIGIN = 0x20020000, LENGTH = 512K
}

/* Alias for stack placement */
REGION_ALIAS("RAM", RAM_NS);

SECTIONS
{
    /* Interrupt vector table */
    .isr_vector :
    {
        . = ALIGN(4);
        KEEP(*(.isr_vector))
        . = ALIGN(4);
    } >FLASH_NS

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
    } >FLASH_NS

    /* Read-only data */
    .rodata :
    {
        . = ALIGN(4);
        *(.rodata)
        *(.rodata*)
        . = ALIGN(4);
    } >FLASH_NS

    /* ARM exception handling */
    .ARM.extab :
    {
        *(.ARM.extab* .gnu.linkonce.armextab.*)
    } >FLASH_NS

    .ARM :
    {
        __exidx_start = .;
        *(.ARM.exidx*)
        __exidx_end = .;
    } >FLASH_NS

    /* Constructors */
    .preinit_array :
    {
        PROVIDE_HIDDEN(__preinit_array_start = .);
        KEEP(*(.preinit_array*))
        PROVIDE_HIDDEN(__preinit_array_end = .);
    } >FLASH_NS

    .init_array :
    {
        PROVIDE_HIDDEN(__init_array_start = .);
        KEEP(*(SORT(.init_array.*)))
        KEEP(*(.init_array*))
        PROVIDE_HIDDEN(__init_array_end = .);
    } >FLASH_NS

    .fini_array :
    {
        PROVIDE_HIDDEN(__fini_array_start = .);
        KEEP(*(SORT(.fini_array.*)))
        KEEP(*(.fini_array*))
        PROVIDE_HIDDEN(__fini_array_end = .);
    } >FLASH_NS

    /* Used by startup to initialize data */
    _sidata = LOADADDR(.data);

    /* Initialized data (includes GOT for position-independent code) */
    .data :
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data)
        *(.data*)
        *(.got)
        *(.got*)
        . = ALIGN(4);
        _edata = .;
    } >RAM_NS AT> FLASH_NS

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
    } >RAM_NS

    /* ThreadX required symbols */
    __RAM_segment_used_end__ = _ebss;
    _vectors = ORIGIN(FLASH_NS);

    /* ThreadX memory area */
    .tx_free_mem :
    {
        . = ALIGN(8);
        __tx_free_memory_start = .;
        . = . + 16K;
        . = ALIGN(8);
    } >RAM_NS

    /* User heap and stack */
    ._user_heap_stack :
    {
        . = ALIGN(8);
        PROVIDE(end = .);
        PROVIDE(_end = .);
        . = . + _Min_Heap_Size;
        . = . + _Min_Stack_Size;
        . = ALIGN(8);
    } >RAM_NS

    /* Discard unused sections */
    /DISCARD/ :
    {
        libc.a(*)
        libm.a(*)
        libgcc.a(*)
    }

    .ARM.attributes 0 : { *(.ARM.attributes) }
}
