/**
 * @file    secure_nsc.h
 * @brief   Non-Secure Callable function prototypes
 *
 * This header is shared between Secure and Non-Secure projects.
 * Non-Secure code includes this to call secure gateway functions.
 */

#ifndef SECURE_NSC_H
#define SECURE_NSC_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* Maximum message length for SECURE_UART_Print */
#define SECURE_UART_MAX_MSG_LEN  256U

/* NSC entry attribute */
#if defined(__ARM_FEATURE_CMSE) && (__ARM_FEATURE_CMSE == 3U)
/* Secure side: mark as NSC entry point */
#define CMSE_NS_ENTRY  __attribute__((cmse_nonsecure_entry))
#else
/* Non-Secure side: just a normal function declaration */
#define CMSE_NS_ENTRY
#endif

/**
 * @brief  Print debug message via secure USART1
 * @param  msg: null-terminated string in NS memory
 * @param  len: message length (max SECURE_UART_MAX_MSG_LEN)
 * @retval 0 on success, -1 on error
 */
int32_t SECURE_UART_Print(const char *msg, uint32_t len);

/**
 * @brief  Get TrustZone security status
 * @retval Status bitmask (bit0: SAU enabled, bit1: GTZC configured)
 */
uint32_t SECURE_GetSecurityStatus(void);

/**
 * @brief  Toggle secure LED (controlled access from NS world)
 */
void SECURE_LED_Toggle(void);

#ifdef __cplusplus
}
#endif

#endif /* SECURE_NSC_H */
