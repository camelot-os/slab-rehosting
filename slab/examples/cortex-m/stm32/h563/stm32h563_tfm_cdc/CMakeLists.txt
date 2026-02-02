# Copyright 2024-2026 Mathieu Renard <mathieu.renard@twistedwires.io>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.22)

# STM32H563 TF-M CDC ACM - Non-Secure Application
# Author: Mathieu Renard <mathieu.renard@twistedwires.io>
#
# Prerequisites:
#   1. TF-M must be built first (cd build/tfm && make)
#   2. STM32CubeH5 SDK at SDK/STM32CubeH5
#
# Build:
#   mkdir build_ns && cd build_ns
#   cmake .. && make

set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)

# Toolchain
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_OBJCOPY arm-none-eabi-objcopy)
set(CMAKE_SIZE arm-none-eabi-size)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

project(stm32h563_tfm_cdc_ns C ASM)

# ---- Required Paths ----
if(NOT DEFINED TFM_BUILD_PATH)
    set(TFM_BUILD_PATH "${CMAKE_SOURCE_DIR}/build/tfm"
        CACHE PATH "Path to TF-M build directory")
endif()

if(NOT DEFINED TFM_SOURCE_PATH)
    set(TFM_SOURCE_PATH "${CMAKE_SOURCE_DIR}/SDK/tf-m"
        CACHE PATH "Path to TF-M source directory")
endif()

if(NOT DEFINED STM32CUBE_H5_PATH)
    set(STM32CUBE_H5_PATH "${CMAKE_SOURCE_DIR}/SDK/STM32CubeH5"
        CACHE PATH "Path to STM32CubeH5 repository")
endif()

# Verify TF-M build exists
if(NOT EXISTS "${TFM_BUILD_PATH}/secure_fw/s_veneers.o")
    message(FATAL_ERROR
        "TF-M build not found at ${TFM_BUILD_PATH}\n"
        "Build TF-M first using: cd build/tfm && make")
endif()

# ---- Paths ----
set(HAL_DRIVER_PATH "${STM32CUBE_H5_PATH}/Drivers/STM32H5xx_HAL_Driver")
set(CMSIS_PATH "${STM32CUBE_H5_PATH}/Drivers/CMSIS")
set(CMSIS_DEVICE_PATH "${CMSIS_PATH}/Device/ST/STM32H5xx")
set(THREADX_PATH "${STM32CUBE_H5_PATH}/Middlewares/ST/threadx")
set(USBX_PATH "${STM32CUBE_H5_PATH}/Middlewares/ST/usbx")
set(TFM_INTERFACE_PATH "${TFM_SOURCE_PATH}/interface")
set(TFM_GENERATED_PATH "${TFM_BUILD_PATH}/generated/interface/include")
set(TFM_PLATFORM_PATH "${TFM_SOURCE_PATH}/platform")

# ---- Compiler Flags ----
set(CPU_FLAGS "-mcpu=cortex-m33 -mthumb -mfpu=fpv5-sp-d16 -mfloat-abi=hard")
set(CMAKE_C_FLAGS "${CPU_FLAGS} -Wall -fdata-sections -ffunction-sections -O2")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -DSTM32H563xx -DUSE_HAL_DRIVER")

# ANSSI Security Hardening Flags (PA-073 recommendations)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fstack-protector-strong")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Wformat -Wformat-security")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fno-common")
# Note: -D_FORTIFY_SOURCE=2 requires optimization; enable in Release

# TF-M NS configuration
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -DTFM_PSA_API -DCONFIG_TFM_ENABLE_FP")
# ThreadX configuration
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -DTX_SINGLE_MODE_NON_SECURE -DTX_INCLUDE_USER_DEFINE_FILE")
# USBX configuration
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -DUX_INCLUDE_USER_DEFINE_FILE")

# ASM flags must include ThreadX TrustZone configuration
set(CMAKE_ASM_FLAGS "${CPU_FLAGS} -DTX_SINGLE_MODE_NON_SECURE")

# ---- Linker ----
set(LINKER_SCRIPT "${CMAKE_SOURCE_DIR}/app_ns/STM32CubeIDE/STM32H563ZITX_FLASH_NS.ld")
set(CMAKE_EXE_LINKER_FLAGS "${CPU_FLAGS} -T${LINKER_SCRIPT}")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--gc-sections -Wl,-Map=tfm_ns_app.map")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -specs=nano.specs -specs=nosys.specs")

# ---- Application Sources ----
set(APP_SOURCES
    app_ns/Src/main.c
    app_ns/Src/psa_crypto_app.c
    app_ns/Src/app_usbx_device.c
    app_ns/Src/ux_device_cdc_acm.c
    app_ns/Src/ux_device_descriptors.c
    app_ns/Src/stm32h5xx_it.c
    app_ns/Src/system_stm32h5xx_ns.c
)

# ---- HAL Sources ----
set(HAL_SOURCES
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
)

# ---- ThreadX Sources ----
file(GLOB THREADX_COMMON_SOURCES "${THREADX_PATH}/common/src/*.c")
file(GLOB THREADX_PORT_SOURCES "${THREADX_PATH}/ports/cortex_m33/gnu/src/*.S")

# ---- USBX Sources ----
file(GLOB USBX_CORE_SOURCES "${USBX_PATH}/common/core/src/*.c")
file(GLOB USBX_CDC_SOURCES "${USBX_PATH}/common/usbx_device_classes/src/ux_device_class_cdc_acm*.c")
file(GLOB USBX_DCD_SOURCES "${USBX_PATH}/common/usbx_stm32_device_controllers/*.c")

# ---- TF-M NS Interface Sources (PSA API) ----
set(TFM_NS_SOURCES
    ${TFM_INTERFACE_PATH}/src/tfm_crypto_api.c
    ${TFM_INTERFACE_PATH}/src/tfm_its_api.c
    ${TFM_INTERFACE_PATH}/src/tfm_ps_api.c
    ${TFM_INTERFACE_PATH}/src/tfm_attest_api.c
    ${TFM_INTERFACE_PATH}/src/tfm_platform_api.c
    ${TFM_INTERFACE_PATH}/src/tfm_tz_psa_ns_api.c
    ${TFM_INTERFACE_PATH}/src/os_wrapper/tfm_ns_interface_bare_metal.c
)

# ---- Startup ----
set(STARTUP_SOURCE
    ${CMSIS_DEVICE_PATH}/Source/Templates/gcc/startup_stm32h563xx.s
)

# ---- Include Directories ----
set(APP_INCLUDES
    app_ns/Inc
    ${HAL_DRIVER_PATH}/Inc
    ${CMSIS_PATH}/Include
    ${CMSIS_DEVICE_PATH}/Include
    # TF-M PSA interface headers
    ${TFM_INTERFACE_PATH}/include
    ${TFM_INTERFACE_PATH}/include/crypto_keys
    ${TFM_GENERATED_PATH}
    ${TFM_GENERATED_PATH}/psa
    ${TFM_PLATFORM_PATH}/include
    # ThreadX
    ${THREADX_PATH}/common/inc
    ${THREADX_PATH}/ports/cortex_m33/gnu/inc
    # USBX
    ${USBX_PATH}/common/core/inc
    ${USBX_PATH}/common/usbx_device_classes/inc
    ${USBX_PATH}/ports/generic/inc
    ${USBX_PATH}/common/usbx_stm32_device_controllers
)

# ---- Build Target ----
add_executable(tfm_ns_app
    ${APP_SOURCES}
    ${HAL_SOURCES}
    ${THREADX_COMMON_SOURCES}
    ${THREADX_PORT_SOURCES}
    ${USBX_CORE_SOURCES}
    ${USBX_CDC_SOURCES}
    ${USBX_DCD_SOURCES}
    ${TFM_NS_SOURCES}
    ${STARTUP_SOURCE}
)

target_include_directories(tfm_ns_app PRIVATE ${APP_INCLUDES})

set_target_properties(tfm_ns_app PROPERTIES
    SUFFIX ".elf"
    C_STANDARD 11
)

# Link against TF-M NS interface (secure veneers)
target_link_libraries(tfm_ns_app PRIVATE
    ${TFM_BUILD_PATH}/secure_fw/s_veneers.o
)

# Generate hex and bin
add_custom_command(TARGET tfm_ns_app POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O ihex $<TARGET_FILE:tfm_ns_app> tfm_ns_app.hex
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:tfm_ns_app> tfm_ns_app.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:tfm_ns_app>
    COMMENT "Generating tfm_ns_app.hex and tfm_ns_app.bin"
)
