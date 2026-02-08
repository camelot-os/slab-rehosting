#
# STM32WB55 CDC Blinky - Native WB55 HAL
#

######################################
# Target
######################################
TARGET = WB55_CDC_Blinky

######################################
# Building variables
######################################
DEBUG = 1
OPT = -Og

#######################################
# Paths
#######################################
BUILD_DIR = build

# STM32CubeWB path (git submodule)
CUBE_DIR = STM32CubeWB

######################################
# Source files
######################################
C_SOURCES = \
Src/main.c \
Src/stm32wbxx_it.c \
Src/usbd_conf.c \
Src/usbd_desc.c \
Src/usbd_cdc_if.c \
Src/usb_device.c \
Src/system_stm32wbxx.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_cortex.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_rcc.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_rcc_ex.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_flash.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_flash_ex.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_gpio.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_dma.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_pwr.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_pwr_ex.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_tim.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_tim_ex.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_pcd.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_pcd_ex.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_ll_usb.c \
$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Src/stm32wbxx_hal_exti.c \
$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Core/Src/usbd_core.c \
$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Core/Src/usbd_ctlreq.c \
$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Core/Src/usbd_ioreq.c \
$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Src/usbd_cdc.c

# ASM sources
ASM_SOURCES = startup_stm32wb55xx.s

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
CPU = -mcpu=cortex-m4
FPU = -mfpu=fpv4-sp-d16
FLOAT-ABI = -mfloat-abi=hard
MCU = $(CPU) -mthumb $(FPU) $(FLOAT-ABI)

AS_DEFS =

C_DEFS = \
-DUSE_HAL_DRIVER \
-DSTM32WB55xx \
-DCORE_CM4

C_INCLUDES = \
-IInc \
-I$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Inc \
-I$(CUBE_DIR)/Drivers/STM32WBxx_HAL_Driver/Inc/Legacy \
-I$(CUBE_DIR)/Drivers/CMSIS/Device/ST/STM32WBxx/Include \
-I$(CUBE_DIR)/Drivers/CMSIS/Include \
-I$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Core/Inc \
-I$(CUBE_DIR)/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc

ASFLAGS = $(MCU) $(AS_DEFS) $(AS_INCLUDES) $(OPT) -Wall -fdata-sections -ffunction-sections

CFLAGS = $(MCU) $(C_DEFS) $(C_INCLUDES) $(OPT) -Wall -fdata-sections -ffunction-sections

ifeq ($(DEBUG), 1)
CFLAGS += -g -gdwarf-2
endif

CFLAGS += -MMD -MP -MF"$(@:%.o=%.d)"

#######################################
# LDFLAGS
#######################################
LDSCRIPT = STM32WB55RGVx_FLASH.ld

LIBS = -lc -lm -lnosys
LIBDIR =
LDFLAGS = $(MCU) -specs=nano.specs -T$(LDSCRIPT) $(LIBDIR) $(LIBS) -Wl,-Map=$(BUILD_DIR)/$(TARGET).map,--cref -Wl,--gc-sections

# Default target
all: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).hex $(BUILD_DIR)/$(TARGET).bin

#######################################
# Build rules
#######################################
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
# Dependencies
#######################################
-include $(wildcard $(BUILD_DIR)/*.d)

.PHONY: all clean
