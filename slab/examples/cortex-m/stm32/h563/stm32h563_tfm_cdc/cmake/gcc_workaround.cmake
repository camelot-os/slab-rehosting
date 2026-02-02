# Workaround for GCC 12.x ICE on stm32h5xx_hal_dma_ex.c
# The compiler crashes during GIMPLE pass: evrp in function HAL_DMAEx_List_ReplaceNode_Head
# Reducing optimization to -O1 for this file avoids the crash

# Find the problematic source file in TF-M platform
set(DMA_EX_FILE "${CMAKE_SOURCE_DIR}/platform/ext/target/stm/common/stm32h5xx/hal/Src/stm32h5xx_hal_dma_ex.c")

if(EXISTS "${DMA_EX_FILE}")
    set_source_files_properties(${DMA_EX_FILE}
        PROPERTIES
        COMPILE_FLAGS "-O1"
    )
    message(STATUS "Applied GCC ICE workaround: -O1 for stm32h5xx_hal_dma_ex.c")
endif()
