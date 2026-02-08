# STM32F405 Blinky Makefile (CubeMX HAL)
#
# Copyright (C) 2025 Twisted Wires Security Lab
# SPDX-License-Identifier: GPL-2.0-or-later

# Target
TARGET = blinky

# Toolchain
PREFIX = arm-none-eabi-
CC = $(PREFIX)gcc
AS = $(PREFIX)gcc -x assembler-with-cpp
CP = $(PREFIX)objcopy
SZ = $(PREFIX)size

# Paths
EXAMPLES_DIR = ../../../../..
REPOS_DIR = $(EXAMPLES_DIR)/repos
CUBE_DIR = $(REPOS_DIR)/STM32CubeF4
HAL_DIR = $(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver
CMSIS_DIR = $(CUBE_DIR)/Drivers/CMSIS

# Build directory
BUILD_DIR = build

# Source files
C_SOURCES = \
    main.c \
    stm32f4xx_it.c \
    system_stm32f4xx.c \
    $(HAL_DIR)/Src/stm32f4xx_hal.c \
    $(HAL_DIR)/Src/stm32f4xx_hal_cortex.c \
    $(HAL_DIR)/Src/stm32f4xx_hal_gpio.c \
    $(HAL_DIR)/Src/stm32f4xx_hal_rcc.c \
    $(HAL_DIR)/Src/stm32f4xx_hal_rcc_ex.c \
    $(HAL_DIR)/Src/stm32f4xx_hal_pwr.c \
    $(HAL_DIR)/Src/stm32f4xx_hal_pwr_ex.c \
    $(HAL_DIR)/Src/stm32f4xx_hal_flash.c \
    $(HAL_DIR)/Src/stm32f4xx_hal_flash_ex.c

ASM_SOURCES = \
    startup_stm32f405xx.s

# Include paths
C_INCLUDES = \
    -I. \
    -I$(HAL_DIR)/Inc \
    -I$(CMSIS_DIR)/Device/ST/STM32F4xx/Include \
    -I$(CMSIS_DIR)/Include

# Compiler flags
CPU = -mcpu=cortex-m4
FPU = -mfpu=fpv4-sp-d16
FLOAT-ABI = -mfloat-abi=hard
MCU = $(CPU) -mthumb $(FPU) $(FLOAT-ABI)

C_DEFS = \
    -DSTM32F405xx \
    -DUSE_HAL_DRIVER

CFLAGS = $(MCU) $(C_DEFS) $(C_INCLUDES) -O2 -Wall -fdata-sections -ffunction-sections
ASFLAGS = $(MCU) -Wall -fdata-sections -ffunction-sections

# Linker flags
LDSCRIPT = STM32F405RGTx_FLASH.ld
LIBS = -lc -lm -lnosys
LDFLAGS = $(MCU) -specs=nano.specs -T$(LDSCRIPT) $(LIBS) -Wl,-Map=$(BUILD_DIR)/$(TARGET).map,--cref -Wl,--gc-sections

# Build rules
all: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).bin

# Object files
OBJECTS = $(addprefix $(BUILD_DIR)/,$(notdir $(C_SOURCES:.c=.o)))
vpath %.c $(sort $(dir $(C_SOURCES)))

OBJECTS += $(addprefix $(BUILD_DIR)/,$(notdir $(ASM_SOURCES:.s=.o)))
vpath %.s $(sort $(dir $(ASM_SOURCES)))

$(BUILD_DIR)/%.o: %.c Makefile | $(BUILD_DIR)
	$(CC) -c $(CFLAGS) $< -o $@

$(BUILD_DIR)/%.o: %.s Makefile | $(BUILD_DIR)
	$(AS) -c $(ASFLAGS) $< -o $@

$(BUILD_DIR)/$(TARGET).elf: $(OBJECTS) Makefile
	$(CC) $(OBJECTS) $(LDFLAGS) -o $@
	$(SZ) $@

$(BUILD_DIR)/%.bin: $(BUILD_DIR)/%.elf
	$(CP) -O binary $< $@

$(BUILD_DIR):
	mkdir -p $@

clean:
	rm -rf $(BUILD_DIR)

# Check if repos exist
check-repos:
	@if [ ! -d "$(CUBE_DIR)" ]; then \
		echo "Error: STM32CubeF4 not found. Run setup_repos.sh first."; \
		exit 1; \
	fi

.PHONY: all clean check-repos
