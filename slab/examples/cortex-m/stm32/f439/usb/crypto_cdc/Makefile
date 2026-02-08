# STM32F439 Crypto Test Firmware Makefile
#
# Author: Mathieu Renard <mathieu.renard@twistedwires.io>
# Copyright (C) 2025 Twisted Wires Security Lab
# SPDX-License-Identifier: GPL-2.0-or-later

TARGET = stm32_crypto_cdc

# Toolchain
CROSS_COMPILE ?= arm-none-eabi-
CC = $(CROSS_COMPILE)gcc
LD = $(CROSS_COMPILE)ld
OBJCOPY = $(CROSS_COMPILE)objcopy
SIZE = $(CROSS_COMPILE)size

# Paths
INCLUDE_DIR = ../../include

# Compiler flags
CFLAGS = -mcpu=cortex-m4 -mthumb -mfloat-abi=soft
CFLAGS += -Os -g -Wall -Wextra
CFLAGS += -ffunction-sections -fdata-sections
CFLAGS += -I$(INCLUDE_DIR)
CFLAGS += -nostdlib -nostartfiles

# Linker flags
LDFLAGS = -T linker.ld
LDFLAGS += --gc-sections
LDFLAGS += -nostdlib

# Sources
SOURCES = main.c
OBJECTS = $(SOURCES:.c=.o)

# Rules
all: $(TARGET).bin $(TARGET).elf

$(TARGET).elf: $(OBJECTS)
	$(CC) $(CFLAGS) $(OBJECTS) -Wl,-T,linker.ld -Wl,--gc-sections -o $@
	$(SIZE) $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJECTS) $(TARGET).elf $(TARGET).bin

.PHONY: all clean
