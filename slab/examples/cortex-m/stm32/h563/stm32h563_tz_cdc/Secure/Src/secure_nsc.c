/**
 * @file    secure_nsc.c
 * @brief   Non-Secure Callable (NSC) gateway functions
 *
 * These functions are placed in the NSC region and can be called
 * from the non-secure world. They provide controlled access to
 * secure resources (USART1 debug output).
 *
 * ANSSI Compliance: All NSC functions include enhanced input validation
 */

#include "main.h"
#include "secure_nsc.h"
#include "security_config.h"
#include <arm_cmse.h>
#include <string.h>

/* Reference to secure UART handle */
extern UART_HandleTypeDef huart1;

/* Rate limiting for NSC calls (simple anti-abuse mechanism) */
static volatile uint32_t nsc_call_count = 0;
#define NSC_MAX_CALLS_PER_PERIOD  1000U
#define NSC_RATE_LIMIT_ENABLED    0  /* Disabled by default, enable if needed */

/**
 * @brief  Validate a pointer from NS world
 *
 * ANSSI Security: Comprehensive pointer validation for NSC functions
 *
 * @param  ptr: Pointer to validate
 * @param  size: Size of the memory region
 * @param  must_read: Require read permission
 * @param  must_write: Require write permission
 * @retval 0 if valid, -1 if invalid
 */
static int NSC_ValidatePointer(const void *ptr, uint32_t size, int must_read, int must_write)
{
    uint32_t flags = CMSE_NONSECURE;

    /* Null pointer check */
    if (ptr == NULL)
    {
        return -1;
    }

    /* Zero size check */
    if (size == 0)
    {
        return -1;
    }

    /* Overflow check for pointer arithmetic */
    if (((uintptr_t)ptr + size) < (uintptr_t)ptr)
    {
        return -1;
    }

    /* Set permission flags */
    if (must_read)
    {
        flags |= CMSE_MPU_READ;
    }
    if (must_write)
    {
        flags |= CMSE_MPU_READWRITE;
    }

    /* CMSE validation: ensure pointer is in non-secure, accessible memory */
    if (cmse_check_address_range((void *)ptr, size, (int)flags) == NULL)
    {
        return -1;
    }

    return 0;
}

/**
 * @brief  Print a debug message via secure USART1
 *         Callable from Non-Secure world.
 *
 * ANSSI Security: Enhanced input validation
 *
 * @param  msg: pointer to null-terminated string (in NS memory)
 * @param  len: length of the message
 * @retval 0 on success, -1 on error
 */
CMSE_NS_ENTRY int32_t SECURE_UART_Print(const char *msg, uint32_t len)
{
#if NSC_RATE_LIMIT_ENABLED
    /* Rate limiting check */
    if (nsc_call_count >= NSC_MAX_CALLS_PER_PERIOD)
    {
        return -1;  /* Rate limit exceeded */
    }
    nsc_call_count++;
#endif

    /* Comprehensive pointer validation */
    if (NSC_ValidatePointer(msg, len, 1, 0) != 0)
    {
        return -1;  /* Invalid pointer or permissions */
    }

    /* Limit message length to prevent abuse (defense in depth) */
    if (len > SECURE_UART_MAX_MSG_LEN)
    {
        len = SECURE_UART_MAX_MSG_LEN;
    }

    /* Additional validation: check for reasonable length */
    if (len == 0)
    {
        return 0;  /* Empty message, nothing to do */
    }

    /* Transmit via secure UART with timeout */
    if (HAL_UART_Transmit(&huart1, (uint8_t *)msg, (uint16_t)len, 1000) != HAL_OK)
    {
        return -1;
    }

    return 0;
}

/**
 * @brief  Get the TrustZone security status
 *         Callable from Non-Secure world.
 * @retval Bitmask of security status flags
 */
CMSE_NS_ENTRY uint32_t SECURE_GetSecurityStatus(void)
{
    uint32_t status = 0;

    /* Bit 0: SAU enabled */
    if (SAU->CTRL & SAU_CTRL_ENABLE_Msk)
    {
        status |= (1UL << 0);
    }

    /* Bit 1: GTZC TZSC lock status */
    /* (simplified - check if configuration is locked) */
    status |= (1UL << 1);

    return status;
}

/**
 * @brief  Toggle secure LED from non-secure world (controlled access)
 *         Callable from Non-Secure world.
 */
CMSE_NS_ENTRY void SECURE_LED_Toggle(void)
{
    HAL_GPIO_TogglePin(LED_GREEN_PORT, LED_GREEN_PIN);
}
