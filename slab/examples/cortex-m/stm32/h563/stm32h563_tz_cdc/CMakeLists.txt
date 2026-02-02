cmake_minimum_required(VERSION 3.22)

# STM32H563 TrustZone CDC ACM Project
# Build order: Secure first (generates NSC veneers), then NonSecure

set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)

# Toolchain
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_OBJCOPY arm-none-eabi-objcopy)
set(CMAKE_SIZE arm-none-eabi-size)

# Prevent CMake from testing the compiler
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

project(stm32h563_tz_cdc C ASM)

# ---- Path Configuration ----
# Set STM32CubeH5 path (clone from https://github.com/STMicroelectronics/STM32CubeH5)
if(NOT DEFINED STM32CUBE_H5_PATH)
    set(STM32CUBE_H5_PATH "${CMAKE_SOURCE_DIR}/SDK/STM32CubeH5" CACHE PATH "Path to STM32CubeH5 repository")
endif()

set(HAL_DRIVER_PATH "${STM32CUBE_H5_PATH}/Drivers/STM32H5xx_HAL_Driver")
set(CMSIS_PATH "${STM32CUBE_H5_PATH}/Drivers/CMSIS")
set(CMSIS_DEVICE_PATH "${CMSIS_PATH}/Device/ST/STM32H5xx")
set(THREADX_PATH "${STM32CUBE_H5_PATH}/Middlewares/ST/threadx")
set(USBX_PATH "${STM32CUBE_H5_PATH}/Middlewares/ST/usbx")

# ---- Common Flags ----
# Secure firmware uses hard float, NS uses soft float (QEMU TrustZone FPU limitation)
set(CPU_FLAGS_SECURE "-mcpu=cortex-m33 -mthumb -mfpu=fpv5-sp-d16 -mfloat-abi=hard")
set(CPU_FLAGS_NS "-mcpu=cortex-m33 -mthumb -mfloat-abi=soft")

# Base flags without CPU-specific settings
set(BASE_C_FLAGS "-Wall -Wextra -fdata-sections -ffunction-sections -fstack-usage")
set(BASE_C_FLAGS "${BASE_C_FLAGS} -DSTM32H563xx -DUSE_HAL_DRIVER")

# ---- ANSSI Security Hardening Flags ----
# Stack protection against buffer overflows
set(BASE_C_FLAGS "${BASE_C_FLAGS} -fstack-protector-strong")
# Fortify source for runtime buffer overflow detection
set(BASE_C_FLAGS "${BASE_C_FLAGS} -D_FORTIFY_SOURCE=2")
# Format string vulnerability protection
set(BASE_C_FLAGS "${BASE_C_FLAGS} -Wformat -Wformat-security -Werror=format-security")
# Additional security warnings
set(BASE_C_FLAGS "${BASE_C_FLAGS} -Wconversion -Wsign-conversion -Wstrict-overflow=2")
# Position independent code (for ASLR when applicable)
set(BASE_C_FLAGS "${BASE_C_FLAGS} -fPIC")
# Trap on signed overflow (undefined behavior)
set(BASE_C_FLAGS "${BASE_C_FLAGS} -ftrapv")

# ============================================================
# SECURE PROJECT
# ============================================================
set(SECURE_C_FLAGS_STR "${CPU_FLAGS_SECURE} ${BASE_C_FLAGS} -mcmse -DSECURE_WORLD")
separate_arguments(SECURE_C_FLAGS UNIX_COMMAND "${SECURE_C_FLAGS_STR}")
set(SECURE_LINKER_SCRIPT "${CMAKE_SOURCE_DIR}/Secure/STM32CubeIDE/STM32H563ZITX_FLASH_S.ld")
set(SECURE_LINK_FLAGS_STR "${CPU_FLAGS_SECURE} -T${SECURE_LINKER_SCRIPT} -Wl,--gc-sections -Wl,--cmse-implib -Wl,--out-implib=${CMAKE_BINARY_DIR}/secure_nsc_lib.o -specs=nano.specs -specs=nosys.specs")
separate_arguments(SECURE_LINK_FLAGS UNIX_COMMAND "${SECURE_LINK_FLAGS_STR}")

# Secure sources
set(SECURE_SOURCES
    Secure/Src/main.c
    Secure/Src/secure_nsc.c
    Secure/Src/stm32h5xx_it.c
    Secure/Src/system_stm32h5xx_s.c
    # HAL sources (from STM32CubeH5)
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_cortex.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_gpio.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_gtzc.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_pwr.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_pwr_ex.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_rcc.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_rcc_ex.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_uart.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_uart_ex.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_flash.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_flash_ex.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_icache.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_iwdg.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_dma.c
    # Startup (from CMSIS)
    ${CMSIS_DEVICE_PATH}/Source/Templates/gcc/startup_stm32h563xx.s
)

# Secure include directories
set(SECURE_INCLUDES
    Secure/Inc
    Secure_nsclib
    ${HAL_DRIVER_PATH}/Inc
    ${CMSIS_PATH}/Include
    ${CMSIS_DEVICE_PATH}/Include
)

add_executable(secure_fw ${SECURE_SOURCES})
target_include_directories(secure_fw PRIVATE ${SECURE_INCLUDES})
set_target_properties(secure_fw PROPERTIES
    SUFFIX ".elf"
    C_STANDARD 11
)
target_compile_options(secure_fw PRIVATE ${SECURE_C_FLAGS})
target_link_options(secure_fw PRIVATE ${SECURE_LINK_FLAGS})

# Generate hex and bin
add_custom_command(TARGET secure_fw POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O ihex $<TARGET_FILE:secure_fw> secure_fw.hex
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:secure_fw> secure_fw.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:secure_fw>
    COMMENT "Generating secure_fw.hex and secure_fw.bin"
)

# ============================================================
# NON-SECURE PROJECT
# ============================================================
# NONSECURE_WORLD enables NS address override in stm32h5xx_hal_conf.h
# (SysTick at 0xE002E010, SCB at 0xE002ED00, NVIC at 0xE002E100)
# Uses soft float since QEMU TrustZone doesn't fully emulate NSACR for FPU access
set(NONSECURE_C_FLAGS_STR "${CPU_FLAGS_NS} ${BASE_C_FLAGS} -DNONSECURE_WORLD -DTX_INCLUDE_USER_DEFINE_FILE -DUX_INCLUDE_USER_DEFINE_FILE")
separate_arguments(NONSECURE_C_FLAGS UNIX_COMMAND "${NONSECURE_C_FLAGS_STR}")
set(NONSECURE_LINKER_SCRIPT "${CMAKE_SOURCE_DIR}/NonSecure/STM32CubeIDE/STM32H563ZITX_FLASH_NS.ld")
set(NONSECURE_LINK_FLAGS_STR "${CPU_FLAGS_NS} -T${NONSECURE_LINKER_SCRIPT} -Wl,--gc-sections -specs=nano.specs -specs=nosys.specs")
separate_arguments(NONSECURE_LINK_FLAGS UNIX_COMMAND "${NONSECURE_LINK_FLAGS_STR}")

# ThreadX sources (minimal set for RTOS functionality)
file(GLOB THREADX_COMMON_SOURCES "${THREADX_PATH}/common/src/*.c")
file(GLOB THREADX_PORT_SOURCES "${THREADX_PATH}/ports/cortex_m33/gnu/src/*.S")

# USBX sources (device mode + CDC ACM class)
file(GLOB USBX_CORE_SOURCES "${USBX_PATH}/common/core/src/*.c")
file(GLOB USBX_CDC_SOURCES "${USBX_PATH}/common/usbx_device_classes/src/ux_device_class_cdc_acm*.c")
file(GLOB USBX_DCD_SOURCES "${USBX_PATH}/common/usbx_stm32_device_controllers/*.c")

# NonSecure sources
set(NONSECURE_SOURCES
    NonSecure/Src/main.c
    NonSecure/Src/app_usbx_device.c
    NonSecure/Src/ux_device_cdc_acm.c
    NonSecure/Src/ux_device_descriptors.c
    NonSecure/Src/stm32h5xx_it.c
    NonSecure/Src/system_stm32h5xx_ns.c
    # HAL sources
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_cortex.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_gpio.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_pcd.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_pcd_ex.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_pwr.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_pwr_ex.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_rcc.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_rcc_ex.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_flash.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_flash_ex.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_icache.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_hal_dma.c
    ${HAL_DRIVER_PATH}/Src/stm32h5xx_ll_usb.c
    # Startup
    ${CMSIS_DEVICE_PATH}/Source/Templates/gcc/startup_stm32h563xx.s
    # ThreadX and USBX
    ${THREADX_COMMON_SOURCES}
    ${THREADX_PORT_SOURCES}
    ${USBX_CORE_SOURCES}
    ${USBX_CDC_SOURCES}
    ${USBX_DCD_SOURCES}
)

# NonSecure include directories
set(NONSECURE_INCLUDES
    NonSecure/Inc
    Secure_nsclib
    ${HAL_DRIVER_PATH}/Inc
    ${CMSIS_PATH}/Include
    ${CMSIS_DEVICE_PATH}/Include
    ${THREADX_PATH}/common/inc
    ${THREADX_PATH}/ports/cortex_m33/gnu/inc
    ${USBX_PATH}/common/core/inc
    ${USBX_PATH}/common/usbx_device_classes/inc
    ${USBX_PATH}/ports/generic/inc
    ${USBX_PATH}/common/usbx_stm32_device_controllers
)

add_executable(nonsecure_fw ${NONSECURE_SOURCES})
target_include_directories(nonsecure_fw PRIVATE ${NONSECURE_INCLUDES})
set_target_properties(nonsecure_fw PROPERTIES
    SUFFIX ".elf"
    C_STANDARD 11
)
target_compile_options(nonsecure_fw PRIVATE ${NONSECURE_C_FLAGS})
target_link_options(nonsecure_fw PRIVATE ${NONSECURE_LINK_FLAGS})

# Link against secure NSC import library
target_link_libraries(nonsecure_fw PRIVATE ${CMAKE_BINARY_DIR}/secure_nsc_lib.o)

# NonSecure depends on Secure (needs NSC lib)
add_dependencies(nonsecure_fw secure_fw)

# Generate hex and bin
add_custom_command(TARGET nonsecure_fw POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O ihex $<TARGET_FILE:nonsecure_fw> nonsecure_fw.hex
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:nonsecure_fw> nonsecure_fw.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:nonsecure_fw>
    COMMENT "Generating nonsecure_fw.hex and nonsecure_fw.bin"
)

# ============================================================
# Flash targets (using STM32CubeProgrammer)
# ============================================================
add_custom_target(flash_secure
    COMMAND STM32_Programmer_CLI -c port=SWD -w secure_fw.bin 0x0C000000 -v
    DEPENDS secure_fw
    COMMENT "Flashing Secure firmware to 0x0C000000"
)

add_custom_target(flash_nonsecure
    COMMAND STM32_Programmer_CLI -c port=SWD -w nonsecure_fw.bin 0x08042000 -v
    DEPENDS nonsecure_fw
    COMMENT "Flashing Non-Secure firmware to 0x08042000"
)

add_custom_target(flash_all
    DEPENDS flash_secure flash_nonsecure
    COMMENT "Flashing both Secure and Non-Secure firmware"
)

# Option bytes target: Enable TrustZone
add_custom_target(configure_option_bytes
    COMMAND STM32_Programmer_CLI -c port=SWD -ob TZEN=1 SECWM_PSTRT=0x0 SECWM_PEND=0x7F
    COMMENT "Configuring Option Bytes: TZEN=1, Secure flash watermark"
)
