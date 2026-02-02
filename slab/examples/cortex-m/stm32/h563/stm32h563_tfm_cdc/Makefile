# STM32H563 TF-M CDC ACM - Makefile
# Self-contained build with SDK submodule

.PHONY: all clean flash_secure flash_nonsecure flash_bl2 flash_all configure_tz setup help

# Build directory
BUILD_DIR := build

# TF-M build directory
TFM_BUILD_DIR := $(BUILD_DIR)/tfm

# Default target
all: $(BUILD_DIR)/app_ns.elf

# Setup SDK and TF-M submodules
setup:
	@echo "=== Setting up SDK submodules ==="
	@if [ -d .git ]; then \
		git submodule update --init --recursive; \
	else \
		echo "Not a git repo, cloning dependencies manually..."; \
		if [ ! -d SDK/STM32CubeH5 ]; then \
			git clone --depth 1 https://github.com/STMicroelectronics/STM32CubeH5.git SDK/STM32CubeH5; \
		fi; \
		if [ ! -d SDK/tf-m ]; then \
			git clone --depth 1 --branch TF-Mv2.0.0 https://git.trustedfirmware.org/TF-M/trusted-firmware-m.git SDK/tf-m; \
		fi; \
		if [ ! -d SDK/mcuboot ]; then \
			git clone --depth 1 --branch v2.0.0 https://github.com/mcu-tools/mcuboot.git SDK/mcuboot; \
		fi; \
	fi
	@echo "=== Setup complete ==="

# Configure TF-M
$(TFM_BUILD_DIR)/Makefile: tfm_config/tfm_build.cmake | setup
	@mkdir -p $(TFM_BUILD_DIR)
	cd $(TFM_BUILD_DIR) && cmake \
		-DTFM_PLATFORM=stm/stm32h573i_dk \
		-DTFM_TOOLCHAIN_FILE=$(CURDIR)/SDK/tf-m/toolchain_GNUARM.cmake \
		-DCMAKE_BUILD_TYPE=Release \
		-C $(CURDIR)/tfm_config/tfm_build.cmake \
		$(CURDIR)/SDK/tf-m

# Build TF-M secure firmware
$(TFM_BUILD_DIR)/bin/tfm_s.bin: $(TFM_BUILD_DIR)/Makefile
	$(MAKE) -C $(TFM_BUILD_DIR) tfm_s

# Build BL2 (MCUboot)
$(TFM_BUILD_DIR)/bin/bl2.bin: $(TFM_BUILD_DIR)/Makefile
	$(MAKE) -C $(TFM_BUILD_DIR) bl2

# Build NS application
$(BUILD_DIR)/Makefile: app_ns/CMakeLists.txt $(TFM_BUILD_DIR)/bin/tfm_s.bin
	@mkdir -p $(BUILD_DIR)
	cd $(BUILD_DIR) && cmake \
		-DSTM32CUBE_H5_PATH=$(CURDIR)/SDK/STM32CubeH5 \
		-DTFM_BUILD_DIR=$(CURDIR)/$(TFM_BUILD_DIR) \
		$(CURDIR)/app_ns

$(BUILD_DIR)/app_ns.elf: $(BUILD_DIR)/Makefile
	$(MAKE) -C $(BUILD_DIR) app_ns

# Flash targets
flash_bl2: $(TFM_BUILD_DIR)/bin/bl2.bin
	STM32_Programmer_CLI -c port=SWD -w $(TFM_BUILD_DIR)/bin/bl2.bin 0x0C000000 -v

flash_secure: $(TFM_BUILD_DIR)/bin/tfm_s.bin
	STM32_Programmer_CLI -c port=SWD -w $(TFM_BUILD_DIR)/bin/tfm_s_signed.bin 0x0C020000 -v

flash_nonsecure: $(BUILD_DIR)/app_ns.elf
	STM32_Programmer_CLI -c port=SWD -w $(BUILD_DIR)/app_ns_signed.bin 0x08040000 -v

flash_all: flash_bl2 flash_secure flash_nonsecure

# Configure TrustZone option bytes (run once)
configure_tz:
	@echo "=== Configuring TrustZone Option Bytes for TF-M ==="
	@echo "WARNING: This modifies device option bytes!"
	@read -p "Continue? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	STM32_Programmer_CLI -c port=SWD -ob TZEN=1 SECWM_PSTRT=0x0 SECWM_PEND=0x7F
	@echo "=== TrustZone configured ==="

# Read option bytes
read_optbytes:
	STM32_Programmer_CLI -c port=SWD -ob displ

# Erase chip
erase:
	STM32_Programmer_CLI -c port=SWD -e all

# Clean build
clean:
	rm -rf $(BUILD_DIR)

# Help
help:
	@echo "STM32H563 TF-M CDC ACM Demo"
	@echo ""
	@echo "Usage:"
	@echo "  make setup          - Initialize SDK/TF-M submodules"
	@echo "  make                - Build all firmware images"
	@echo "  make flash_all      - Flash all images to device"
	@echo "  make flash_bl2      - Flash bootloader (MCUboot)"
	@echo "  make flash_secure   - Flash TF-M secure firmware"
	@echo "  make flash_nonsecure - Flash non-secure application"
	@echo "  make configure_tz   - Configure TrustZone option bytes (once)"
	@echo "  make read_optbytes  - Read current option bytes"
	@echo "  make clean          - Remove build directory"
	@echo ""
	@echo "Requirements:"
	@echo "  - arm-none-eabi-gcc toolchain"
	@echo "  - CMake 3.22+"
	@echo "  - Python 3 with cbor, cryptography packages"
	@echo "  - STM32CubeProgrammer (for flashing)"
