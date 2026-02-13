#!/usr/bin/env python3
"""
Exercise 02: Peripheral Modeling

Learn how to create and interact with virtual peripherals
for ARM Cortex-M emulation.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0

OBJECTIVES:
1. Create virtual GPIO peripheral
2. Implement LED toggling
3. Set up UART communication
4. Build a simple peripheral bridge

DIFFICULTY: Intermediate
TIME: 45 minutes
"""

# TODO: Import required components
# from slab_cortex_m import VirtualLED, VirtualButton, VirtualUART, STM32GPIO

def exercise_2_1():
    """
    Task 2.1: Virtual LED

    Create a virtual LED on pin 5.
    Toggle it 5 times and print the state each time.
    """
    # YOUR CODE HERE
    pass


def exercise_2_2():
    """
    Task 2.2: Button with callback

    Create a virtual button that:
    - Prints "Button pressed!" when pressed
    - Prints "Button released!" when released

    Simulate 3 press/release cycles.
    """
    # YOUR CODE HERE
    pass


def exercise_2_3():
    """
    Task 2.3: UART loopback

    Create a virtual UART at 115200 baud.
    Write "Hello, MCU!" and read it back.
    Verify the data matches.
    """
    # YOUR CODE HERE
    pass


def exercise_2_4():
    """
    Task 2.4: GPIO register access

    Create an STM32 GPIO peripheral at base 0x40020000.
    - Write 0x55AA to the ODR register
    - Read it back and verify
    - Toggle specific bits using BSRR
    """
    # YOUR CODE HERE
    pass


def verify_solutions():
    """Verify your solutions are correct."""
    print("Verifying Exercise 02 solutions...")
    print("All tasks completed!")


if __name__ == '__main__':
    print("=" * 60)
    print("Exercise 02: Peripheral Modeling")
    print("=" * 60)

    print("\nTask 2.1: Virtual LED")
    exercise_2_1()

    print("\nTask 2.2: Button with callback")
    exercise_2_2()

    print("\nTask 2.3: UART loopback")
    exercise_2_3()

    print("\nTask 2.4: GPIO register access")
    exercise_2_4()

    print("\n" + "=" * 60)
    verify_solutions()
