/**
 * @file    tx_user.h
 * @brief   ThreadX user configuration
 */

#ifndef TX_USER_H
#define TX_USER_H

/* ThreadX configuration overrides */
#define TX_MAX_PRIORITIES               32
#define TX_TIMER_TICKS_PER_SECOND       1000
#define TX_DISABLE_PREEMPTION_THRESHOLD
#define TX_DISABLE_REDUNDANT_CLEARING
#define TX_TIMER_PROCESS_IN_ISR
#define TX_REACTIVATE_INLINE
#define TX_INLINE_THREAD_RESUME_SUSPEND

/* IMPORTANT: Disable TrustZone secure mode features */
/* We're running as NS-only and don't need secure stack management */
#define TX_SINGLE_MODE_NON_SECURE

#endif /* TX_USER_H */
