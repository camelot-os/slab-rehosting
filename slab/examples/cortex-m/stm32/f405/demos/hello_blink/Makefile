#
# HelloBlink - STM32F405 USB CDC Demo
#

######################################
# Target
######################################
TARGET = HelloBlink

######################################
# Building variables
######################################
DEBUG = 1
OPT = -Og

#######################################
# Paths
#######################################
BUILD_DIR = build

# STM32CubeF4 path (git submodule)
CUBE_DIR = STM32CubeF4

######################################
# Source files
######################################
# C sources
C_SOURCES =  \
Src/main.c \
Src/stm32f4xx_it.c \
Src/usbd_conf.c \
Src/usbd_desc.c \
Src/usbd_cdc_if.c \
Src/system_stm32f4xx.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_cortex.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_rcc.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_rcc_ex.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_flash.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_flash_ex.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_gpio.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_dma.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_pwr.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_pwr_ex.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_tim.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_tim_ex.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_pcd.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_pcd_ex.c \
$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_ll_usb.c \
$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Core/Src/usbd_core.c \
$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Core/Src/usbd_ctlreq.c \
$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Core/Src/usbd_ioreq.c \
$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Src/usbd_cdc.c

# ASM sources
ASM_SOURCES = startup_stm32f405xx.s

#######################################
# Toolchain
#######################################
PREFIX = arm-none-eabi-
CC = $(PREFIX)gcc
AS = $(PREFIX)gcc -x assembler-with-cpp
CP = $(PREFIX)objcopy
SZ = $(PREFIX)size

HEX = $(CP) -O ihex
BIN = $(CP) -O binary -S

#######################################
# CFLAGS
#######################################
# CPU
CPU = -mcpu=cortex-m4

# FPU
FPU = -mfpu=fpv4-sp-d16
FLOAT-ABI = -mfloat-abi=hard

# MCU
MCU = $(CPU) -mthumb $(FPU) $(FLOAT-ABI)

# Macros
AS_DEFS =

C_DEFS =  \
-DUSE_HAL_DRIVER \
-DSTM32F405xx \
-DUSE_USB_FS

# Include paths
C_INCLUDES =  \
-IInc \
-I$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Inc \
-I$(CUBE_DIR)/Drivers/STM32F4xx_HAL_Driver/Inc/Legacy \
-I$(CUBE_DIR)/Drivers/CMSIS/Device/ST/STM32F4xx/Include \
-I$(CUBE_DIR)/Drivers/CMSIS/Include \
-I$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Core/Inc \
-I$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc

# Compile flags
ASFLAGS = $(MCU) $(AS_DEFS) $(AS_INCLUDES) $(OPT) -Wall -fdata-sections -ffunction-sections

CFLAGS = $(MCU) $(C_DEFS) $(C_INCLUDES) $(OPT) -Wall -fdata-sections -ffunction-sections

ifeq ($(DEBUG), 1)
CFLAGS += -g -gdwarf-2
endif

# Generate dependency files
CFLAGS += -MMD -MP -MF"$(@:%.o=%.d)"

#######################################
# LDFLAGS
#######################################
# Linker script
LDSCRIPT = STM32F405RGTx_FLASH.ld

# Libraries
LIBS = -lc -lm -lnosys
LIBDIR =
LDFLAGS = $(MCU) -specs=nano.specs -T$(LDSCRIPT) $(LIBDIR) $(LIBS) -Wl,-Map=$(BUILD_DIR)/$(TARGET).map,--cref -Wl,--gc-sections

# Default target
all: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).hex $(BUILD_DIR)/$(TARGET).bin

#######################################
# Build rules
#######################################
# List of objects
OBJECTS = $(addprefix $(BUILD_DIR)/,$(notdir $(C_SOURCES:.c=.o)))
vpath %.c $(sort $(dir $(C_SOURCES)))
OBJECTS += $(addprefix $(BUILD_DIR)/,$(notdir $(ASM_SOURCES:.s=.o)))
vpath %.s $(sort $(dir $(ASM_SOURCES)))

$(BUILD_DIR)/%.o: %.c Makefile | $(BUILD_DIR)
	$(CC) -c $(CFLAGS) -Wa,-a,-ad,-alms=$(BUILD_DIR)/$(notdir $(<:.c=.lst)) $< -o $@

$(BUILD_DIR)/%.o: %.s Makefile | $(BUILD_DIR)
	$(AS) -c $(ASFLAGS) $< -o $@

$(BUILD_DIR)/$(TARGET).elf: $(OBJECTS) Makefile
	$(CC) $(OBJECTS) $(LDFLAGS) -o $@
	$(SZ) $@

$(BUILD_DIR)/%.hex: $(BUILD_DIR)/%.elf | $(BUILD_DIR)
	$(HEX) $< $@

$(BUILD_DIR)/%.bin: $(BUILD_DIR)/%.elf | $(BUILD_DIR)
	$(BIN) $< $@

$(BUILD_DIR):
	mkdir $@

#######################################
# Clean
#######################################
clean:
	-rm -fR $(BUILD_DIR)

#######################################
# Flash with st-flash or OpenOCD
#######################################
flash: $(BUILD_DIR)/$(TARGET).bin
	st-flash write $< 0x8000000

flash-openocd: $(BUILD_DIR)/$(TARGET).elf
	openocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c "program $< verify reset exit"

#######################################
# Dependencies
#######################################
-include $(wildcard $(BUILD_DIR)/*.d)

.PHONY: all clean flash flash-openocd
