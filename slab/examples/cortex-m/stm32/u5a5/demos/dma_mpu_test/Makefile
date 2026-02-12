#
# STM32U5A5 DMA + MPU Test
#
# GPDMA1 memory-to-memory transfer + PMSAv8 MPU validation
# Target: Nucleo-U5A5ZJT6Q (Cortex-M33 @ 160 MHz)
#

######################################
# Target
######################################
TARGET = U5A5_DMA_MPU_Test

######################################
# Building variables
######################################
DEBUG = 1
OPT = -Og

#######################################
# Paths
#######################################
BUILD_DIR = build

# STM32CubeU5 path (symlink to ../../../../../repos/STM32CubeU5)
CUBE_DIR = STM32CubeU5

######################################
# Source files
######################################
C_SOURCES = \
Src/main.c \
Src/stm32u5xx_it.c \
Src/system_stm32u5xx.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_cortex.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_rcc.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_rcc_ex.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_flash.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_flash_ex.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_gpio.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_dma.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_dma_ex.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_pwr.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_pwr_ex.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_uart.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_uart_ex.c \
$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Src/stm32u5xx_hal_exti.c

# ASM sources
ASM_SOURCES = startup_stm32u5a5xx.s

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
CPU = -mcpu=cortex-m33

MCU = $(CPU) -mthumb

AS_DEFS =

C_DEFS = \
-DUSE_HAL_DRIVER \
-DSTM32U5A5xx

C_INCLUDES = \
-IInc \
-I$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Inc \
-I$(CUBE_DIR)/Drivers/STM32U5xx_HAL_Driver/Inc/Legacy \
-I$(CUBE_DIR)/Drivers/CMSIS/Device/ST/STM32U5xx/Include \
-I$(CUBE_DIR)/Drivers/CMSIS/Include

ASFLAGS = $(MCU) $(AS_DEFS) $(AS_INCLUDES) $(OPT) -Wall -fdata-sections -ffunction-sections

CFLAGS = $(MCU) $(C_DEFS) $(C_INCLUDES) $(OPT) -Wall -fdata-sections -ffunction-sections

ifeq ($(DEBUG), 1)
CFLAGS += -g -gdwarf-2
endif

CFLAGS += -MMD -MP -MF"$(@:%.o=%.d)"

#######################################
# LDFLAGS
#######################################
LDSCRIPT = STM32U5A5ZJTXQ_FLASH.ld

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
