#!/usr/bin/env python3
"""
Setup script for slab-mcp package.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from setuptools import setup, find_packages

setup(
    name="slab-mcp",
    version="0.1.0",
    author="Mathieu Renard",
    author_email="mathieu.renard@twistedwires.io",
    description="Slab MCP Server - Model Context Protocol with subpackage discovery",
    long_description=open("../../README.md").read() if __import__("os").path.exists("../../README.md") else "",
    long_description_content_type="text/markdown",
    url="https://github.com/twistedwires/slab",
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
    ],
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        # No hard dependencies - discovers other slab packages at runtime
    ],
    extras_require={
        "full": [
            "slab-cortex-m>=0.1.0",
            "slab-cortex-a>=0.1.0",
            "slab-timing>=0.1.0",
            "slab-sidechannels>=0.1.0",
            "slab-glitch>=0.1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "slab-mcp-server=slab_mcp.server:main",
        ],
    },
    keywords=[
        "slab",
        "mcp",
        "model-context-protocol",
        "arm",
        "emulator",
        "security",
    ],
)
