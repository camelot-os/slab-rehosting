/*
 * Copyright 2024-2026 Mathieu Renard <mathieu.renard@twistedwires.io>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * @file    tx_user.h
 * @brief   ThreadX user configuration (TF-M project)
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 */

#ifndef TX_USER_H
#define TX_USER_H

/* TrustZone: Run ThreadX in non-secure mode */
#ifndef TX_SINGLE_MODE_NON_SECURE
#define TX_SINGLE_MODE_NON_SECURE
#endif

#define TX_MAX_PRIORITIES               32
#define TX_TIMER_TICKS_PER_SECOND       1000
#define TX_DISABLE_PREEMPTION_THRESHOLD
#define TX_DISABLE_REDUNDANT_CLEARING
#define TX_TIMER_PROCESS_IN_ISR
#define TX_REACTIVATE_INLINE
#define TX_INLINE_THREAD_RESUME_SUSPEND

#endif /* TX_USER_H */
