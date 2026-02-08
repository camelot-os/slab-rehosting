"""
STM32 UART compatibility alias.

Re-exports from stm32_usart for backward compatibility.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from .stm32_usart import STM32USARTv1, STM32USARTv2  # noqa: F401
