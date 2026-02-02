/**
 * Linker script for STM32H563ZI - Non-Secure world (TF-M project)
 * TF-M occupies secure flash; NS app starts at 0x08042000
 */

ENTRY(Reset_Handler)

_estack = ORIGIN(RAM) + LENGTH(RAM);
_Min_Heap_Size = 0x4000;   /* 16KB for PSA crypto buffers */
_Min_Stack_Size = 0x2000;  /* 8KB */

MEMORY
{
    FLASH_NS  (rx)  : ORIGIN = 0x08042000, LENGTH = 1784K
    RAM_NS    (rwx) : ORIGIN = 0x20020000, LENGTH = 512K
}

REGION_ALIAS("RAM", RAM_NS);

SECTIONS
{
    /* ThreadX requires _vectors symbol pointing to vector table */
    .isr_vector :
    {
        . = ALIGN(4);
        _vectors = .;
        KEEP(*(.isr_vector))
        . = ALIGN(4);
    } >FLASH_NS

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

    .rodata :
    {
        . = ALIGN(4);
        *(.rodata)
        *(.rodata*)
        . = ALIGN(4);
    } >FLASH_NS

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

    _sidata = LOADADDR(.data);

    .data :
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data)
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } >RAM_NS AT> FLASH_NS

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

    /* ThreadX free memory - symbol required by tx_initialize_low_level.S */
    .tx_free_mem :
    {
        . = ALIGN(8);
        __tx_free_memory_start = .;
        __RAM_segment_used_end__ = .;
        . = . + 32K;
        . = ALIGN(8);
    } >RAM_NS

    ._user_heap_stack :
    {
        . = ALIGN(8);
        PROVIDE(end = .);
        PROVIDE(_end = .);
        . = . + _Min_Heap_Size;
        . = . + _Min_Stack_Size;
        . = ALIGN(8);
    } >RAM_NS

    /DISCARD/ :
    {
        libc.a(*)
        libm.a(*)
        libgcc.a(*)
    }

    .ARM.attributes 0 : { *(.ARM.attributes) }
}
