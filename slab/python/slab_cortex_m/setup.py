#!/usr/bin/env python3
"""
Setup script for slab-cortex-m package.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from setuptools import setup, find_packages

setup(
    name="slab-cortex-m",
    version="0.1.0",
    author="Mathieu Renard",
    author_email="mathieu.renard@twistedwires.io",
    description="ARM Cortex-M emulation core for Slab",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    url="https://github.com/twistedwires/slab",
    project_urls={
        "Bug Tracker": "https://github.com/twistedwires/slab/issues",
        "Documentation": "https://slab.readthedocs.io/",
        "Source": "https://github.com/twistedwires/slab",
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Security",
        "Topic :: System :: Emulators",
        "Topic :: Software Development :: Embedded Systems",
    ],
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "numpy>=1.20.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "mypy>=1.0.0",
        ],
        "gui": [
            "pygame>=2.0.0",
        ],
        "usb": [
            "pyusb>=1.2.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "slab-server=slab_cortex_m.mcuemu_server:main",
        ],
    },
    keywords=[
        "arm",
        "cortex-m",
        "emulator",
        "embedded",
        "security",
        "svd",
        "qemu",
    ],
)
