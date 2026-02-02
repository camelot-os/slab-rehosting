#!/bin/bash
# Apply patches to TF-M to work around compiler bugs

TFM_DIR="$1"

if [ -z "$TFM_DIR" ]; then
    echo "Usage: $0 <tfm_directory>"
    exit 1
fi

# Workaround for GCC 12.x ICE on stm32h5xx_hal_dma_ex.c
# Add set_source_files_properties to reduce optimization for the problematic file
STM32H5_CMAKE="$TFM_DIR/platform/ext/target/stm/common/stm32h5xx/CMakeLists.txt"

if [ -f "$STM32H5_CMAKE" ]; then
    if ! grep -q "GCC ICE workaround" "$STM32H5_CMAKE"; then
        echo "Applying GCC ICE workaround to $STM32H5_CMAKE..."
        cat >> "$STM32H5_CMAKE" << 'EOF'

# GCC ICE workaround: GCC 12.x crashes on stm32h5xx_hal_dma_ex.c during evrp pass
# Reduce optimization to -O1 for this file
if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
    set_source_files_properties(
        ${CMAKE_CURRENT_SOURCE_DIR}/hal/Src/stm32h5xx_hal_dma_ex.c
        PROPERTIES COMPILE_FLAGS "-O1"
    )
endif()
EOF
        echo "Patch applied successfully."
    else
        echo "Patch already applied."
    fi
else
    echo "Error: $STM32H5_CMAKE not found"
    exit 1
fi
