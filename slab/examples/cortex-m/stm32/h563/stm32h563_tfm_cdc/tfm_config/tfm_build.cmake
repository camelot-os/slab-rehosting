# TF-M Build Configuration for STM32H563 CDC ACM Example
#
# This file is passed to TF-M's CMake build via -C flag:
#   cmake -S <tfm-src> -B build_spe -C <this-file>

# Target platform (existing TF-M port)
set(TFM_PLATFORM "stm/stm32h5xx" CACHE STRING "TF-M platform")

# Toolchain
set(TFM_TOOLCHAIN_FILE "toolchain_GNUARM.cmake" CACHE STRING "TF-M toolchain")

# Isolation level 1: SFN model (Secure Functions, simpler, lower overhead)
# Level 2/3 use IPC model (more isolation, higher memory usage)
set(TFM_ISOLATION_LEVEL 1 CACHE STRING "PSA isolation level")

# Enable PSA services
set(TFM_PARTITION_CRYPTO ON CACHE BOOL "PSA Crypto service")
set(TFM_PARTITION_PROTECTED_STORAGE ON CACHE BOOL "PSA Protected Storage")
set(TFM_PARTITION_INTERNAL_TRUSTED_STORAGE ON CACHE BOOL "PSA Internal Trusted Storage")
set(TFM_PARTITION_INITIAL_ATTESTATION ON CACHE BOOL "PSA Initial Attestation")
set(TFM_PARTITION_PLATFORM ON CACHE BOOL "Platform service")

# Crypto configuration
set(CRYPTO_HW_ACCELERATOR ON CACHE BOOL "Use STM32 hardware crypto accelerator")

# Build type
set(CMAKE_BUILD_TYPE "RelWithDebInfo" CACHE STRING "Build type")

# BL2 bootloader (MCUboot) - ENABLED for secure boot chain (ANSSI requirement)
# This enables image signature verification and secure firmware updates
set(BL2 ON CACHE BOOL "Enable MCUboot bootloader")

# MCUboot configuration for secure boot
set(MCUBOOT_IMAGE_NUMBER 2 CACHE STRING "Number of images (S + NS)")
set(MCUBOOT_SIGNATURE_TYPE "RSA-3072" CACHE STRING "Signature algorithm")
set(MCUBOOT_HW_KEY ON CACHE BOOL "Use hardware key for verification")

# Debug UART output from TF-M
set(TFM_PARTITION_LOG_LEVEL TFM_PARTITION_LOG_LEVEL_INFO CACHE STRING "Log level")

# Test suite (disable for production)
set(TEST_S OFF CACHE BOOL "Secure regression tests")
set(TEST_NS OFF CACHE BOOL "Non-secure regression tests")
