/**
 * @file    security_config.h
 * @brief   Security configuration for STM32H563 TrustZone project
 *
 * ANSSI compliance settings and production security features.
 * This file centralizes all security-related configuration options.
 *
 * WARNING: For production deployment:
 *   1. Set PRODUCTION_MODE to 1
 *   2. Configure RDP Level 2 via STM32CubeProgrammer (IRREVERSIBLE)
 *   3. Enable BOOT_LOCK option byte
 */

#ifndef SECURITY_CONFIG_H
#define SECURITY_CONFIG_H

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================================
 * PRODUCTION MODE CONFIGURATION
 * ============================================================================
 * Set to 1 for production builds. This enables:
 * - Debug interface lockout (SWD disabled)
 * - Verbose error messages disabled
 * - Additional security checks
 */
#ifndef PRODUCTION_MODE
#define PRODUCTION_MODE             0
#endif

/* ============================================================================
 * DEBUG INTERFACE PROTECTION (ANSSI Critical)
 * ============================================================================
 * In production mode, the debug interface (SWD/JTAG) is locked to prevent:
 * - Firmware extraction
 * - Memory inspection
 * - Debug-based attacks
 */
#if PRODUCTION_MODE
#define SECURITY_LOCK_DEBUG         1   /* Lock SWD/JTAG in production */
#else
#define SECURITY_LOCK_DEBUG         0   /* Allow debugging in development */
#endif

/* ============================================================================
 * FLASH PROTECTION / READ-OUT PROTECTION (RDP)
 * ============================================================================
 * RDP Levels (configured via STM32CubeProgrammer, not runtime):
 *   Level 0: No protection (development only)
 *   Level 1: Flash read protection, can regress to Level 0 (full erase)
 *   Level 2: PERMANENT protection, debug fully disabled (IRREVERSIBLE!)
 *
 * WARNING: RDP Level 2 is IRREVERSIBLE. Test thoroughly with Level 1 first.
 *
 * STM32CubeProgrammer command for RDP Level 1:
 *   STM32_Programmer_CLI -c port=SWD -ob RDP=0xBB
 *
 * STM32CubeProgrammer command for RDP Level 2 (PERMANENT):
 *   STM32_Programmer_CLI -c port=SWD -ob RDP=0xCC
 */
#if PRODUCTION_MODE
#define RECOMMENDED_RDP_LEVEL       2   /* Level 2 for production */
#else
#define RECOMMENDED_RDP_LEVEL       0   /* Level 0 for development */
#endif

/* ============================================================================
 * SECURE BOOT CONFIGURATION
 * ============================================================================
 */
#define SECURITY_VERIFY_NS_IMAGE    1   /* Verify NS image before jump */
#define SECURITY_NS_IMAGE_CRC       1   /* Use CRC32 for quick verification */

/* Expected CRC32 of valid NS image (update after each NS build) */
/* This should be computed from the NS binary and updated in build process */
#ifndef NS_IMAGE_EXPECTED_CRC
#define NS_IMAGE_EXPECTED_CRC       0xFFFFFFFFUL  /* Placeholder - update in build */
#endif

/* NS image validation: minimum valid stack pointer range */
#define NS_STACK_PTR_MIN            0x20020000UL  /* Start of NS SRAM */
#define NS_STACK_PTR_MAX            0x200A0000UL  /* End of NS SRAM */

/* NS image validation: valid reset handler address range */
#define NS_RESET_HANDLER_MIN        0x08042000UL  /* Start of NS Flash */
#define NS_RESET_HANDLER_MAX        0x08200000UL  /* End of Flash */

/* ============================================================================
 * WATCHDOG CONFIGURATION (ANSSI Recommendation)
 * ============================================================================
 */
#define SECURITY_ENABLE_IWDG        1   /* Enable Independent Watchdog */
#define IWDG_TIMEOUT_MS             4000 /* Watchdog timeout in milliseconds */

/* ============================================================================
 * GPDMA SECURITY CONFIGURATION
 * ============================================================================
 * All GPDMA channels must be explicitly configured as secure or non-secure.
 * By default, configure all as non-secure for NS USB operations.
 */
#define SECURITY_CONFIGURE_GPDMA    1   /* Explicitly configure GPDMA channels */

/* ============================================================================
 * MEMORY PROTECTION CONFIGURATION
 * ============================================================================
 */
#define SECURITY_EXPLICIT_SRAM1     1   /* Explicitly configure SRAM1 as secure */

/* ============================================================================
 * ANSSI COMPLIANCE CHECKLIST (for documentation)
 * ============================================================================
 * [ ] Stack protection: -fstack-protector-strong
 * [ ] Format string protection: -Wformat-security -Werror=format-security
 * [ ] Buffer overflow detection: -D_FORTIFY_SOURCE=2
 * [ ] Secure boot chain: MCUboot (BL2) enabled
 * [ ] Debug lockout: SWD disabled in production
 * [ ] Memory isolation: SAU + MPCBB configured
 * [ ] Peripheral isolation: GTZC TZSC configured
 * [ ] Watchdog: IWDG enabled
 * [ ] Crypto: AES-256-GCM (PSA Crypto)
 * [ ] RNG: Hardware TRNG via PSA
 * [ ] Flash protection: RDP Level 1/2
 */

/* ============================================================================
 * ERROR MESSAGE VERBOSITY
 * ============================================================================
 * In production, suppress detailed error codes that could aid attackers.
 */
#if PRODUCTION_MODE
#define SECURITY_VERBOSE_ERRORS     0   /* Generic error messages only */
#else
#define SECURITY_VERBOSE_ERRORS     1   /* Detailed errors for debugging */
#endif

/* ============================================================================
 * INPUT VALIDATION LIMITS
 * ============================================================================
 */
#define MAX_NSC_STRING_LENGTH       256U    /* Max string length for NSC functions */
#define MAX_NSC_BUFFER_SIZE         4096U   /* Max buffer size for NSC functions */

#ifdef __cplusplus
}
#endif

#endif /* SECURITY_CONFIG_H */
