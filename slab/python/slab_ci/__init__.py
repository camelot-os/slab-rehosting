"""
Slab CI - Security Testing CI/CD Module

Enterprise-grade CI/CD module for automated security testing with:
- User authentication and role-based access control
- Configurable test targets and vulnerability definitions
- Side-channel and fault injection test orchestration
- Report generation and notification system

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.1.0"
__author__ = "Mathieu Renard"
__project__ = "Slab"

from .config import (
    TestTarget,
    VulnerableRegion,
    TestConfig,
    ProjectConfig,
)
from .auth import (
    User,
    UserRole,
    Group,
    AuthManager,
)

__all__ = [
    "__version__",
    "TestTarget",
    "VulnerableRegion",
    "TestConfig",
    "ProjectConfig",
    "User",
    "UserRole",
    "Group",
    "AuthManager",
]
