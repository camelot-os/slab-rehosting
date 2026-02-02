# STM32H563 TrustZone CDC ACM - Makefile
# Self-contained build with SDK submodule

.PHONY: all clean flash_secure flash_nonsecure flash_all configure_tz setup help docs

# Build directory
BUILD_DIR := build

# Default target
all: $(BUILD_DIR)/nonsecure_fw.elf

# Setup SDK submodule
setup:
	@echo "=== Setting up SDK ==="
	@if [ -d .git ]; then \
		git submodule update --init --recursive; \
	elif [ ! -d SDK/STM32CubeH5 ]; then \
		echo "Cloning STM32CubeH5..."; \
		git clone --depth 1 --recurse-submodules \
			https://github.com/STMicroelectronics/STM32CubeH5.git SDK/STM32CubeH5; \
	else \
		echo "SDK already present"; \
	fi
	@echo "=== Setup complete ==="

# Configure and build
$(BUILD_DIR)/Makefile: CMakeLists.txt
	@if [ ! -d SDK/STM32CubeH5/Drivers ]; then $(MAKE) setup; fi
	@mkdir -p $(BUILD_DIR)
	cd $(BUILD_DIR) && cmake ..

$(BUILD_DIR)/secure_fw.elf: $(BUILD_DIR)/Makefile
	$(MAKE) -C $(BUILD_DIR) secure_fw

$(BUILD_DIR)/nonsecure_fw.elf: $(BUILD_DIR)/secure_fw.elf
	$(MAKE) -C $(BUILD_DIR) nonsecure_fw

# Flash targets
flash_secure: $(BUILD_DIR)/secure_fw.elf
	STM32_Programmer_CLI -c port=SWD -w $(BUILD_DIR)/secure_fw.bin 0x0C000000 -v

flash_nonsecure: $(BUILD_DIR)/nonsecure_fw.elf
	STM32_Programmer_CLI -c port=SWD -w $(BUILD_DIR)/nonsecure_fw.bin 0x08040000 -v

flash_all: flash_secure flash_nonsecure

# Configure TrustZone option bytes (run once)
configure_tz:
	@echo "=== Configuring TrustZone Option Bytes ==="
	@echo "WARNING: This modifies device option bytes!"
	@read -p "Continue? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	STM32_Programmer_CLI -c port=SWD -ob TZEN=1 SECWM_PSTRT=0x0 SECWM_PEND=0x3F
	@echo "=== TrustZone configured ==="

# Read option bytes
read_optbytes:
	STM32_Programmer_CLI -c port=SWD -ob displ

# Erase chip
erase:
	STM32_Programmer_CLI -c port=SWD -e all

# Build documentation
docs:
	cd docs && make html

# Clean build
clean:
	rm -rf $(BUILD_DIR)

# Help
help:
	@echo "STM32H563 TrustZone CDC ACM Demo"
	@echo ""
	@echo "Usage:"
	@echo "  make setup          - Initialize SDK submodule"
	@echo "  make                - Build both firmware images"
	@echo "  make flash_all      - Flash both images to device"
	@echo "  make flash_secure   - Flash secure firmware only"
	@echo "  make flash_nonsecure - Flash non-secure firmware only"
	@echo "  make configure_tz   - Configure TrustZone option bytes (once)"
	@echo "  make read_optbytes  - Read current option bytes"
	@echo "  make docs           - Build Sphinx documentation"
	@echo "  make clean          - Remove build directory"
	@echo ""
	@echo "Requirements:"
	@echo "  - arm-none-eabi-gcc toolchain"
	@echo "  - CMake 3.22+"
	@echo "  - STM32CubeProgrammer (for flashing)"
