TARGET = pico_dashboard
BUILD_DIR = build

CC = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
SIZE = arm-none-eabi-size

INCLUDES = -I../../include

CFLAGS = -mcpu=cortex-m0plus -mthumb -O2 -Wall -Wextra \
         -ffreestanding -nostdlib $(INCLUDES) \
         -ffunction-sections -fdata-sections

LDFLAGS = -mcpu=cortex-m0plus -mthumb -nostdlib \
          -T../../linker_pico.ld \
          -Wl,--gc-sections -Wl,-Map=$(BUILD_DIR)/$(TARGET).map

SRCS = main.c
OBJS = $(SRCS:%.c=$(BUILD_DIR)/%.o)

all: $(BUILD_DIR)/$(TARGET).bin

$(BUILD_DIR)/$(TARGET).bin: $(BUILD_DIR)/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@
	$(SIZE) $<

$(BUILD_DIR)/$(TARGET).elf: $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $^ -lgcc

$(BUILD_DIR)/%.o: %.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c -o $@ $<

$(BUILD_DIR):
	mkdir -p $@

clean:
	rm -rf $(BUILD_DIR)

.PHONY: all clean
