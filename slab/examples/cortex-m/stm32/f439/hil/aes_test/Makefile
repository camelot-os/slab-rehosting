# STM32F439 AES HIL Test - Bare-metal Makefile
#
# Build: make
# Clean: make clean

PREFIX  = arm-none-eabi-
CC      = $(PREFIX)gcc
OBJCOPY = $(PREFIX)objcopy
SIZE    = $(PREFIX)size

INCLUDES = -I../../include

CFLAGS  = -mcpu=cortex-m4 -mthumb -mfloat-abi=soft \
          -Os -Wall -Wextra -ffreestanding -nostdlib \
          $(INCLUDES)

LDFLAGS = -T ../../soc/stm32f4/linker.ld -nostdlib -Wl,--gc-sections

TARGET  = aes_test

all: build/$(TARGET).bin

build/$(TARGET).elf: main.c
	@mkdir -p build
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	$(SIZE) $@

build/$(TARGET).bin: build/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@

clean:
	rm -rf build

.PHONY: all clean
