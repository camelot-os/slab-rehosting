# FreeRTOS Multi-Task Blinky Makefile
#
# Copyright (C) 2025 Twisted Wires Security Lab
# SPDX-License-Identifier: GPL-2.0-or-later

# Target
TARGET = freertos_blinky

# Toolchain
PREFIX = arm-none-eabi-
CC = $(PREFIX)gcc
AS = $(PREFIX)gcc -x assembler-with-cpp
CP = $(PREFIX)objcopy
SZ = $(PREFIX)size

# Paths
EXAMPLES_DIR = ../../../../..
REPOS_DIR = $(EXAMPLES_DIR)/repos
FREERTOS_DIR = $(REPOS_DIR)/FreeRTOS-Kernel
CMSIS_DIR = $(REPOS_DIR)/CMSIS_5/CMSIS/Core/Include
CUBE_DIR = $(REPOS_DIR)/STM32CubeF4

# Build directory
BUILD_DIR = build

# Source files
C_SOURCES = \
    main.c \
    system_stm32f4xx.c \
    $(FREERTOS_DIR)/tasks.c \
    $(FREERTOS_DIR)/queue.c \
    $(FREERTOS_DIR)/list.c \
    $(FREERTOS_DIR)/timers.c \
    $(FREERTOS_DIR)/portable/GCC/ARM_CM4F/port.c \
    $(FREERTOS_DIR)/portable/MemMang/heap_4.c

ASM_SOURCES = \
    startup_stm32f405xx.s

# Include paths
C_INCLUDES = \
    -I. \
    -I$(FREERTOS_DIR)/include \
    -I$(FREERTOS_DIR)/portable/GCC/ARM_CM4F \
    -I$(CMSIS_DIR) \
    -I$(CUBE_DIR)/Drivers/CMSIS/Device/ST/STM32F4xx/Include

# Compiler flags
CPU = -mcpu=cortex-m4
FPU = -mfpu=fpv4-sp-d16
FLOAT-ABI = -mfloat-abi=hard
MCU = $(CPU) -mthumb $(FPU) $(FLOAT-ABI)

C_DEFS = \
    -DSTM32F405xx \
    -D__FPU_PRESENT=1 \
    -D__FPU_USED=1

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
	@if [ ! -d "$(FREERTOS_DIR)" ]; then \
		echo "Error: FreeRTOS-Kernel not found. Run setup_repos.sh first."; \
		exit 1; \
	fi

.PHONY: all clean check-repos
