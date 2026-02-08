#!/usr/bin/env python3
"""
Exercise 01: SVD Parsing Basics

Learn how to parse SVD files and extract peripheral information
for ARM Cortex-M microcontrollers.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0

OBJECTIVES:
1. Parse an SVD file for STM32F4
2. List all peripherals and their base addresses
3. Find all GPIO-related registers
4. Calculate register addresses from base + offset

DIFFICULTY: Beginner
TIME: 30 minutes
"""

# TODO: Import the SVD parser
# from mcuemu_cortex_m import SVDParser

def exercise_1_1():
    """
    Task 1.1: Parse an SVD file

    Download an STM32F4 SVD file from:
    https://github.com/posborne/cmsis-svd/tree/master/data/STMicro

    Parse it and print the device name.
    """
    # YOUR CODE HERE
    pass


def exercise_1_2():
    """
    Task 1.2: List all peripherals

    After parsing the SVD, iterate through all peripherals
    and print their names and base addresses in hex format.
    """
    # YOUR CODE HERE
    pass


def exercise_1_3():
    """
    Task 1.3: Find GPIO registers

    Find all registers belonging to GPIOA peripheral.
    Print each register's name, offset, and size.
    """
    # YOUR CODE HERE
    pass


def exercise_1_4():
    """
    Task 1.4: Calculate absolute addresses

    For GPIOA peripheral:
    - Get the base address
    - For each register, calculate the absolute address
    - Format output as: "GPIOA->ODR = 0x40020014"
    """
    # YOUR CODE HERE
    pass


# Solution verification
def verify_solutions():
    """Verify your solutions are correct."""
    print("Verifying Exercise 01 solutions...")
    # Add verification logic here
    print("All tasks completed!")


if __name__ == '__main__':
    # Run exercises
    print("=" * 60)
    print("Exercise 01: SVD Parsing Basics")
    print("=" * 60)

    print("\nTask 1.1: Parse SVD file")
    exercise_1_1()

    print("\nTask 1.2: List peripherals")
    exercise_1_2()

    print("\nTask 1.3: Find GPIO registers")
    exercise_1_3()

    print("\nTask 1.4: Calculate addresses")
    exercise_1_4()

    print("\n" + "=" * 60)
    verify_solutions()
