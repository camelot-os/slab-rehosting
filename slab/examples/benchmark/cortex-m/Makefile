# SLAB Benchmark Firmware Build
#
# Targets:
#   all     - Build all firmware variants
#   clean   - Remove build artifacts
#   flash   - Flash to target (if connected)

# Toolchain
PREFIX ?= arm-none-eabi-
CC = $(PREFIX)gcc
AS = $(PREFIX)as
LD = $(PREFIX)ld
OBJCOPY = $(PREFIX)objcopy
OBJDUMP = $(PREFIX)objdump
SIZE = $(PREFIX)size

# CPU variants to build
CPUS = cortex-m0 cortex-m3 cortex-m4 cortex-m7 cortex-m33

# Directories
BUILD_DIR = build
BIN_DIR = bin

# Common flags
COMMON_FLAGS = -mthumb -Wall -Wextra -Os -ffunction-sections -fdata-sections
LDFLAGS = -nostdlib -T stm32f4.ld -Wl,--gc-sections

# Default target
all: dirs $(foreach cpu,$(CPUS),$(BIN_DIR)/benchmark_$(cpu).bin)

dirs:
	@mkdir -p $(BUILD_DIR) $(BIN_DIR)

# Build rules for each CPU variant
$(BIN_DIR)/benchmark_cortex-m0.bin: benchmark.c stm32f4.ld | dirs
	$(CC) $(COMMON_FLAGS) -mcpu=cortex-m0 -c -o $(BUILD_DIR)/benchmark_m0.o $<
	$(CC) $(COMMON_FLAGS) -mcpu=cortex-m0 $(LDFLAGS) -o $(BUILD_DIR)/benchmark_m0.elf $(BUILD_DIR)/benchmark_m0.o
	$(OBJCOPY) -O binary $(BUILD_DIR)/benchmark_m0.elf $@
	$(SIZE) $(BUILD_DIR)/benchmark_m0.elf

$(BIN_DIR)/benchmark_cortex-m3.bin: benchmark.c stm32f4.ld | dirs
	$(CC) $(COMMON_FLAGS) -mcpu=cortex-m3 -c -o $(BUILD_DIR)/benchmark_m3.o $<
	$(CC) $(COMMON_FLAGS) -mcpu=cortex-m3 $(LDFLAGS) -o $(BUILD_DIR)/benchmark_m3.elf $(BUILD_DIR)/benchmark_m3.o
	$(OBJCOPY) -O binary $(BUILD_DIR)/benchmark_m3.elf $@
	$(SIZE) $(BUILD_DIR)/benchmark_m3.elf

$(BIN_DIR)/benchmark_cortex-m4.bin: benchmark.c stm32f4.ld | dirs
	$(CC) $(COMMON_FLAGS) -mcpu=cortex-m4 -mfpu=fpv4-sp-d16 -mfloat-abi=hard -c -o $(BUILD_DIR)/benchmark_m4.o $<
	$(CC) $(COMMON_FLAGS) -mcpu=cortex-m4 -mfpu=fpv4-sp-d16 -mfloat-abi=hard $(LDFLAGS) -o $(BUILD_DIR)/benchmark_m4.elf $(BUILD_DIR)/benchmark_m4.o
	$(OBJCOPY) -O binary $(BUILD_DIR)/benchmark_m4.elf $@
	$(SIZE) $(BUILD_DIR)/benchmark_m4.elf

$(BIN_DIR)/benchmark_cortex-m7.bin: benchmark.c stm32f4.ld | dirs
	$(CC) $(COMMON_FLAGS) -mcpu=cortex-m7 -mfpu=fpv5-sp-d16 -mfloat-abi=hard -c -o $(BUILD_DIR)/benchmark_m7.o $<
	$(CC) $(COMMON_FLAGS) -mcpu=cortex-m7 -mfpu=fpv5-sp-d16 -mfloat-abi=hard $(LDFLAGS) -o $(BUILD_DIR)/benchmark_m7.elf $(BUILD_DIR)/benchmark_m7.o
	$(OBJCOPY) -O binary $(BUILD_DIR)/benchmark_m7.elf $@
	$(SIZE) $(BUILD_DIR)/benchmark_m7.elf

$(BIN_DIR)/benchmark_cortex-m33.bin: benchmark.c stm32f4.ld | dirs
	$(CC) $(COMMON_FLAGS) -mcpu=cortex-m33 -mfpu=fpv5-sp-d16 -mfloat-abi=hard -c -o $(BUILD_DIR)/benchmark_m33.o $<
	$(CC) $(COMMON_FLAGS) -mcpu=cortex-m33 -mfpu=fpv5-sp-d16 -mfloat-abi=hard $(LDFLAGS) -o $(BUILD_DIR)/benchmark_m33.elf $(BUILD_DIR)/benchmark_m33.o
	$(OBJCOPY) -O binary $(BUILD_DIR)/benchmark_m33.elf $@
	$(SIZE) $(BUILD_DIR)/benchmark_m33.elf

# Disassembly (useful for debugging)
disasm: $(BUILD_DIR)/benchmark_m4.elf
	$(OBJDUMP) -d -S $< > $(BUILD_DIR)/benchmark_m4.disasm

# Clean
clean:
	rm -rf $(BUILD_DIR) $(BIN_DIR)

# Flash via OpenOCD (if real hardware is connected)
flash: $(BIN_DIR)/benchmark_cortex-m4.bin
	openocd -f interface/stlink.cfg -f target/stm32f4x.cfg \
		-c "program $< verify reset exit 0x08000000"

# Flash via J-Link
flash-jlink: $(BIN_DIR)/benchmark_cortex-m4.bin
	JLinkExe -device STM32F405RG -if SWD -speed 4000 -autoconnect 1 \
		-CommandFile flash.jlink

.PHONY: all dirs clean flash flash-jlink disasm
