# RP2040 I2C EEPROM Test Firmware Makefile
#
# Author: Mathieu Renard <mathieu.renard@twistedwires.io>
# Copyright (C) 2025 TwistedWires Security Lab
# SPDX-License-Identifier: GPL-2.0-or-later

TARGET = rp2040_eeprom_test

# Toolchain
CROSS_COMPILE ?= arm-none-eabi-
CC = $(CROSS_COMPILE)gcc
LD = $(CROSS_COMPILE)ld
OBJCOPY = $(CROSS_COMPILE)objcopy
SIZE = $(CROSS_COMPILE)size

# Paths
INCLUDE_DIR = ../../include
LINKER_SCRIPT = ../../linker_pico.ld

# Compiler flags - Cortex-M0+ for RP2040
CFLAGS = -mcpu=cortex-m0plus -mthumb
CFLAGS += -Os -g -Wall -Wextra
CFLAGS += -ffunction-sections -fdata-sections
CFLAGS += -fno-builtin
CFLAGS += -I$(INCLUDE_DIR)
CFLAGS += -nostdlib -nostartfiles

# Sources
SOURCES = main.c
OBJECTS = $(SOURCES:.c=.o)

# Rules
all: $(TARGET).bin $(TARGET).elf

$(TARGET).elf: $(OBJECTS)
	$(CC) $(CFLAGS) $(OBJECTS) -Wl,-T,$(LINKER_SCRIPT) -Wl,--gc-sections -o $@
	$(SIZE) $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJECTS) $(TARGET).elf $(TARGET).bin

.PHONY: all clean
