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
 * @file    stm32h5xx_it.c
 * @brief   Non-Secure interrupt handlers (TF-M project)
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 *
 * Note: ThreadX owns the following handlers (defined in tx_initialize_low_level.S):
 *   - SysTick_Handler, HardFault_Handler, UsageFault_Handler
 * ThreadX owns (defined in tx_thread_schedule.S):
 *   - PendSV_Handler, SVC_Handler
 */

#include "main.h"

extern PCD_HandleTypeDef hpcd_USB_DRD_FS;

/* Fault handlers not owned by ThreadX */
void NMI_Handler(void)          { while (1) {} }
void MemManage_Handler(void)    { while (1) {} }
void BusFault_Handler(void)     { while (1) {} }
void DebugMon_Handler(void)     {}

/* USB interrupt handler */
void USB_DRD_FS_IRQHandler(void)
{
    HAL_PCD_IRQHandler(&hpcd_USB_DRD_FS);
}

/**
 * @brief HAL tick increment - called from ThreadX timer ISR
 *
 * ANSSI Note: Proper integration with ThreadX timer.
 * This function should be called from _tx_timer_interrupt
 * or from the application's timer callback.
 */
void HAL_IncTick_Hook(void)
{
    HAL_IncTick();
}
