#!/usr/bin/env python3
"""
MCUemu SLAB - Software Lab for ARM/Cortex-M Peripheral Emulation

Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
"""

from setuptools import setup, find_packages

setup(
    name="slab-cortex-m",
    version="1.0.0",
    description="Peripheral emulation library for Cortex-M microcontrollers",
    long_description=open("../README.md").read(),
    long_description_content_type="text/markdown",
    author="Twisted Wires Security Lab",
    author_email="contact@twistedwires.io",
    url="https://github.com/twistedwires/mcuemu",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "PyYAML>=6.0",
        "cryptography>=41.0",
    ],
    extras_require={
        "gui": ["pygame>=2.5"],
        "mcp": ["mcp>=0.1"],
        "dev": [
            "pytest>=7.0",
            "sphinx>=5.0",
            "furo>=2023.1",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Embedded Systems",
        "Topic :: System :: Emulators",
    ],
    entry_points={
        "console_scripts": [
            "slab-server=slab_cortex_m.mcuemu_server:main",
            "slab-mcp=slab_mcp.server:main",
        ],
    },
)
