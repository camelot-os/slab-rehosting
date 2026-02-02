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
 * @file    ux_user.h
 * @brief   USBX user configuration
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 */

#ifndef UX_USER_H
#define UX_USER_H

/* USBX user configuration - minimal for CDC ACM */
#define UX_THREAD_STACK_SIZE             2048
#define UX_PERIODIC_RATE                 1000

#endif /* UX_USER_H */
