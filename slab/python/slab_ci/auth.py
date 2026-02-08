"""
Slab CI - Authentication and Authorization Module

Enterprise-grade user authentication and role-based access control for
the security testing CI system.

Features:
- User management (create, update, delete)
- Role-based access control (RBAC)
- Group management
- API key authentication
- Session management
- Audit logging

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import hashlib
import secrets
import json
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from enum import Enum, Flag, auto
from pathlib import Path
import base64


class UserRole(Flag):
    """User roles with hierarchical permissions."""
    VIEWER = auto()         # View results only
    TESTER = auto()         # Run tests
    ANALYST = auto()        # View and analyze results
    DEVELOPER = auto()      # Configure targets and tests
    ADMIN = auto()          # Full system access

    # Composite roles
    @classmethod
    def standard(cls) -> "UserRole":
        """Standard user role."""
        return cls.VIEWER | cls.TESTER | cls.ANALYST

    @classmethod
    def power_user(cls) -> "UserRole":
        """Power user role."""
        return cls.standard() | cls.DEVELOPER

    @classmethod
    def full_access(cls) -> "UserRole":
        """Full access role."""
        return cls.VIEWER | cls.TESTER | cls.ANALYST | cls.DEVELOPER | cls.ADMIN


class Permission(Enum):
    """Fine-grained permissions."""
    # Project permissions
    PROJECT_VIEW = "project:view"
    PROJECT_CREATE = "project:create"
    PROJECT_EDIT = "project:edit"
    PROJECT_DELETE = "project:delete"

    # Target permissions
    TARGET_VIEW = "target:view"
    TARGET_CREATE = "target:create"
    TARGET_EDIT = "target:edit"
    TARGET_DELETE = "target:delete"

    # Test permissions
    TEST_VIEW = "test:view"
    TEST_RUN = "test:run"
    TEST_CANCEL = "test:cancel"
    TEST_DELETE = "test:delete"

    # Result permissions
    RESULT_VIEW = "result:view"
    RESULT_EXPORT = "result:export"
    RESULT_DELETE = "result:delete"

    # Report permissions
    REPORT_VIEW = "report:view"
    REPORT_GENERATE = "report:generate"
    REPORT_SHARE = "report:share"

    # User permissions
    USER_VIEW = "user:view"
    USER_CREATE = "user:create"
    USER_EDIT = "user:edit"
    USER_DELETE = "user:delete"

    # Group permissions
    GROUP_VIEW = "group:view"
    GROUP_CREATE = "group:create"
    GROUP_EDIT = "group:edit"
    GROUP_DELETE = "group:delete"

    # System permissions
    SYSTEM_CONFIG = "system:config"
    SYSTEM_AUDIT = "system:audit"
    SYSTEM_BACKUP = "system:backup"


# Role to permissions mapping
ROLE_PERMISSIONS: Dict[UserRole, Set[Permission]] = {
    UserRole.VIEWER: {
        Permission.PROJECT_VIEW,
        Permission.TARGET_VIEW,
        Permission.TEST_VIEW,
        Permission.RESULT_VIEW,
        Permission.REPORT_VIEW,
    },
    UserRole.TESTER: {
        Permission.TEST_RUN,
        Permission.TEST_CANCEL,
        Permission.REPORT_GENERATE,
    },
    UserRole.ANALYST: {
        Permission.RESULT_EXPORT,
        Permission.REPORT_SHARE,
    },
    UserRole.DEVELOPER: {
        Permission.PROJECT_CREATE,
        Permission.PROJECT_EDIT,
        Permission.TARGET_CREATE,
        Permission.TARGET_EDIT,
        Permission.TARGET_DELETE,
        Permission.TEST_DELETE,
        Permission.RESULT_DELETE,
    },
    UserRole.ADMIN: {
        Permission.PROJECT_DELETE,
        Permission.USER_VIEW,
        Permission.USER_CREATE,
        Permission.USER_EDIT,
        Permission.USER_DELETE,
        Permission.GROUP_VIEW,
        Permission.GROUP_CREATE,
        Permission.GROUP_EDIT,
        Permission.GROUP_DELETE,
        Permission.SYSTEM_CONFIG,
        Permission.SYSTEM_AUDIT,
        Permission.SYSTEM_BACKUP,
    },
}


@dataclass
class User:
    """User account."""
    id: str
    username: str
    email: str
    display_name: str = ""
    role: UserRole = UserRole.VIEWER
    groups: List[str] = field(default_factory=list)

    # Authentication
    password_hash: str = ""
    api_key_hash: str = ""
    totp_secret: str = ""       # For 2FA

    # Status
    active: bool = True
    email_verified: bool = False
    created_at: float = field(default_factory=time.time)
    last_login: float = 0
    failed_login_count: int = 0
    locked_until: float = 0

    # Preferences
    notification_email: bool = True
    notification_slack: bool = False
    timezone: str = "UTC"

    def has_permission(self, permission: Permission) -> bool:
        """Check if user has a specific permission."""
        # Check role-based permissions
        for role in UserRole:
            if role in self.role:
                if permission in ROLE_PERMISSIONS.get(role, set()):
                    return True
        return False

    def has_any_permission(self, permissions: List[Permission]) -> bool:
        """Check if user has any of the specified permissions."""
        return any(self.has_permission(p) for p in permissions)

    def has_all_permissions(self, permissions: List[Permission]) -> bool:
        """Check if user has all specified permissions."""
        return all(self.has_permission(p) for p in permissions)

    def get_permissions(self) -> Set[Permission]:
        """Get all permissions for this user."""
        perms = set()
        for role in UserRole:
            if role in self.role:
                perms.update(ROLE_PERMISSIONS.get(role, set()))
        return perms

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role.value,
            "groups": self.groups,
            "active": self.active,
            "email_verified": self.email_verified,
            "created_at": self.created_at,
            "last_login": self.last_login,
            "permissions": [p.value for p in self.get_permissions()],
        }
        if include_sensitive:
            data["password_hash"] = self.password_hash
            data["api_key_hash"] = self.api_key_hash
        return data


@dataclass
class Group:
    """User group for team organization."""
    id: str
    name: str
    description: str = ""

    # Members
    member_ids: List[str] = field(default_factory=list)

    # Permissions (additional to role-based)
    permissions: Set[Permission] = field(default_factory=set)

    # Projects this group has access to
    project_ids: List[str] = field(default_factory=list)

    # Settings
    created_at: float = field(default_factory=time.time)
    created_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "member_ids": self.member_ids,
            "permissions": [p.value for p in self.permissions],
            "project_ids": self.project_ids,
            "created_at": self.created_at,
        }


@dataclass
class Session:
    """User session."""
    id: str
    user_id: str
    token_hash: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0
    ip_address: str = ""
    user_agent: str = ""
    active: bool = True

    def is_valid(self) -> bool:
        """Check if session is still valid."""
        return self.active and time.time() < self.expires_at


@dataclass
class AuditLog:
    """Audit log entry."""
    id: str
    timestamp: float
    user_id: str
    action: str
    resource_type: str
    resource_id: str
    details: Dict[str, Any] = field(default_factory=dict)
    ip_address: str = ""
    success: bool = True


class AuthManager:
    """
    Authentication and authorization manager.

    Handles user authentication, session management, and access control.
    """

    def __init__(self, storage_path: str = "auth_data"):
        """Initialize auth manager."""
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.users: Dict[str, User] = {}
        self.groups: Dict[str, Group] = {}
        self.sessions: Dict[str, Session] = {}
        self.audit_logs: List[AuditLog] = []

        # Configuration
        self.session_duration_hours: int = 24
        self.max_failed_logins: int = 5
        self.lockout_duration_minutes: int = 30
        self.password_min_length: int = 12
        self.require_2fa_for_admin: bool = True

        # Load existing data
        self._load_data()

    def _load_data(self) -> None:
        """Load data from storage."""
        users_file = self.storage_path / "users.json"
        groups_file = self.storage_path / "groups.json"

        if users_file.exists():
            with open(users_file) as f:
                data = json.load(f)
                for u in data:
                    user = User(
                        id=u["id"],
                        username=u["username"],
                        email=u["email"],
                        display_name=u.get("display_name", ""),
                        role=UserRole(u.get("role", UserRole.VIEWER.value)),
                        groups=u.get("groups", []),
                        password_hash=u.get("password_hash", ""),
                        api_key_hash=u.get("api_key_hash", ""),
                        active=u.get("active", True),
                        created_at=u.get("created_at", time.time()),
                    )
                    self.users[user.id] = user

        if groups_file.exists():
            with open(groups_file) as f:
                data = json.load(f)
                for g in data:
                    group = Group(
                        id=g["id"],
                        name=g["name"],
                        description=g.get("description", ""),
                        member_ids=g.get("member_ids", []),
                        project_ids=g.get("project_ids", []),
                    )
                    self.groups[group.id] = group

    def _save_data(self) -> None:
        """Save data to storage."""
        users_file = self.storage_path / "users.json"
        groups_file = self.storage_path / "groups.json"

        with open(users_file, "w") as f:
            json.dump([u.to_dict(include_sensitive=True) for u in self.users.values()], f, indent=2)

        with open(groups_file, "w") as f:
            json.dump([g.to_dict() for g in self.groups.values()], f, indent=2)

    def _hash_password(self, password: str, salt: str = None) -> str:
        """Hash a password with salt."""
        if salt is None:
            salt = secrets.token_hex(16)
        hash_value = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode(),
            salt.encode(),
            100000
        )
        return f"{salt}${hash_value.hex()}"

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against its hash."""
        if not password_hash or '$' not in password_hash:
            return False
        salt, _ = password_hash.split('$', 1)
        return self._hash_password(password, salt) == password_hash

    def _generate_id(self) -> str:
        """Generate a unique ID."""
        return secrets.token_hex(8)

    def _generate_api_key(self) -> tuple:
        """Generate an API key and its hash."""
        key = f"slab_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return key, key_hash

    def _log_action(
        self,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Dict[str, Any] = None,
        success: bool = True,
        ip_address: str = "",
    ) -> None:
        """Log an action for audit."""
        log = AuditLog(
            id=self._generate_id(),
            timestamp=time.time(),
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip_address,
            success=success,
        )
        self.audit_logs.append(log)

        # Keep only last 10000 entries in memory
        if len(self.audit_logs) > 10000:
            self.audit_logs = self.audit_logs[-10000:]

    # =========================================================================
    # User Management
    # =========================================================================

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        display_name: str = "",
        role: UserRole = UserRole.VIEWER,
        created_by: str = "system",
    ) -> User:
        """Create a new user."""
        # Validate
        if len(password) < self.password_min_length:
            raise ValueError(f"Password must be at least {self.password_min_length} characters")

        if any(u.username == username for u in self.users.values()):
            raise ValueError(f"Username '{username}' already exists")

        if any(u.email == email for u in self.users.values()):
            raise ValueError(f"Email '{email}' already registered")

        user = User(
            id=self._generate_id(),
            username=username,
            email=email,
            display_name=display_name or username,
            role=role,
            password_hash=self._hash_password(password),
        )

        self.users[user.id] = user
        self._save_data()
        self._log_action(created_by, "create", "user", user.id, {"username": username})

        return user

    def update_user(
        self,
        user_id: str,
        updated_by: str,
        **kwargs,
    ) -> User:
        """Update user fields."""
        user = self.users.get(user_id)
        if not user:
            raise ValueError(f"User '{user_id}' not found")

        for key, value in kwargs.items():
            if hasattr(user, key) and key not in ('id', 'password_hash', 'api_key_hash'):
                setattr(user, key, value)

        self._save_data()
        self._log_action(updated_by, "update", "user", user_id, kwargs)

        return user

    def delete_user(self, user_id: str, deleted_by: str) -> bool:
        """Delete a user."""
        if user_id not in self.users:
            return False

        username = self.users[user_id].username
        del self.users[user_id]
        self._save_data()
        self._log_action(deleted_by, "delete", "user", user_id, {"username": username})

        return True

    def change_password(
        self,
        user_id: str,
        old_password: str,
        new_password: str,
    ) -> bool:
        """Change user password."""
        user = self.users.get(user_id)
        if not user:
            return False

        if not self._verify_password(old_password, user.password_hash):
            self._log_action(user_id, "change_password", "user", user_id, success=False)
            return False

        if len(new_password) < self.password_min_length:
            raise ValueError(f"Password must be at least {self.password_min_length} characters")

        user.password_hash = self._hash_password(new_password)
        self._save_data()
        self._log_action(user_id, "change_password", "user", user_id)

        return True

    def generate_api_key(self, user_id: str) -> str:
        """Generate a new API key for user. Returns the key (only shown once)."""
        user = self.users.get(user_id)
        if not user:
            raise ValueError(f"User '{user_id}' not found")

        key, key_hash = self._generate_api_key()
        user.api_key_hash = key_hash
        self._save_data()
        self._log_action(user_id, "generate_api_key", "user", user_id)

        return key

    # =========================================================================
    # Authentication
    # =========================================================================

    def authenticate(
        self,
        username: str,
        password: str,
        ip_address: str = "",
    ) -> Optional[str]:
        """
        Authenticate user with username and password.
        Returns session token on success, None on failure.
        """
        user = next(
            (u for u in self.users.values() if u.username == username),
            None
        )

        if not user:
            return None

        # Check if locked
        if user.locked_until > time.time():
            self._log_action(user.id, "login", "user", user.id,
                           {"reason": "locked"}, success=False, ip_address=ip_address)
            return None

        # Verify password
        if not self._verify_password(password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= self.max_failed_logins:
                user.locked_until = time.time() + (self.lockout_duration_minutes * 60)
            self._save_data()
            self._log_action(user.id, "login", "user", user.id,
                           {"reason": "invalid_password"}, success=False, ip_address=ip_address)
            return None

        # Check if active
        if not user.active:
            self._log_action(user.id, "login", "user", user.id,
                           {"reason": "inactive"}, success=False, ip_address=ip_address)
            return None

        # Success - create session
        user.failed_login_count = 0
        user.last_login = time.time()
        self._save_data()

        token = secrets.token_urlsafe(32)
        session = Session(
            id=self._generate_id(),
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=time.time() + (self.session_duration_hours * 3600),
            ip_address=ip_address,
        )
        self.sessions[session.id] = session

        self._log_action(user.id, "login", "user", user.id, ip_address=ip_address)

        return token

    def authenticate_api_key(self, api_key: str) -> Optional[User]:
        """Authenticate using API key. Returns user on success."""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        for user in self.users.values():
            if user.api_key_hash == key_hash and user.active:
                return user

        return None

    def validate_session(self, token: str) -> Optional[User]:
        """Validate session token. Returns user on success."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        for session in self.sessions.values():
            if session.token_hash == token_hash and session.is_valid():
                return self.users.get(session.user_id)

        return None

    def logout(self, token: str) -> bool:
        """Invalidate a session."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        for session_id, session in self.sessions.items():
            if session.token_hash == token_hash:
                session.active = False
                self._log_action(session.user_id, "logout", "session", session_id)
                return True

        return False

    # =========================================================================
    # Group Management
    # =========================================================================

    def create_group(
        self,
        name: str,
        description: str = "",
        created_by: str = "system",
    ) -> Group:
        """Create a new group."""
        if any(g.name == name for g in self.groups.values()):
            raise ValueError(f"Group '{name}' already exists")

        group = Group(
            id=self._generate_id(),
            name=name,
            description=description,
            created_by=created_by,
        )

        self.groups[group.id] = group
        self._save_data()
        self._log_action(created_by, "create", "group", group.id, {"name": name})

        return group

    def add_user_to_group(self, user_id: str, group_id: str, added_by: str) -> bool:
        """Add user to group."""
        user = self.users.get(user_id)
        group = self.groups.get(group_id)

        if not user or not group:
            return False

        if group_id not in user.groups:
            user.groups.append(group_id)
        if user_id not in group.member_ids:
            group.member_ids.append(user_id)

        self._save_data()
        self._log_action(added_by, "add_member", "group", group_id,
                        {"user_id": user_id})

        return True

    def remove_user_from_group(self, user_id: str, group_id: str, removed_by: str) -> bool:
        """Remove user from group."""
        user = self.users.get(user_id)
        group = self.groups.get(group_id)

        if not user or not group:
            return False

        if group_id in user.groups:
            user.groups.remove(group_id)
        if user_id in group.member_ids:
            group.member_ids.remove(user_id)

        self._save_data()
        self._log_action(removed_by, "remove_member", "group", group_id,
                        {"user_id": user_id})

        return True

    # =========================================================================
    # Authorization
    # =========================================================================

    def check_permission(
        self,
        user: User,
        permission: Permission,
        resource_id: str = None,
    ) -> bool:
        """
        Check if user has permission for a resource.

        Checks both role-based and group-based permissions.
        """
        # Check role-based permission
        if user.has_permission(permission):
            return True

        # Check group-based permissions
        for group_id in user.groups:
            group = self.groups.get(group_id)
            if group and permission in group.permissions:
                # Check if group has access to the resource
                if resource_id is None or resource_id in group.project_ids:
                    return True

        return False

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_audit_logs(
        self,
        user_id: str = None,
        action: str = None,
        resource_type: str = None,
        limit: int = 100,
    ) -> List[AuditLog]:
        """Get audit logs with optional filters."""
        logs = self.audit_logs

        if user_id:
            logs = [l for l in logs if l.user_id == user_id]
        if action:
            logs = [l for l in logs if l.action == action]
        if resource_type:
            logs = [l for l in logs if l.resource_type == resource_type]

        return sorted(logs, key=lambda l: l.timestamp, reverse=True)[:limit]

    def list_users(self, active_only: bool = True) -> List[User]:
        """List all users."""
        users = list(self.users.values())
        if active_only:
            users = [u for u in users if u.active]
        return users

    def list_groups(self) -> List[Group]:
        """List all groups."""
        return list(self.groups.values())

    def setup_initial_admin(
        self,
        username: str,
        email: str,
        password: str,
    ) -> User:
        """Set up initial admin user if no users exist."""
        if self.users:
            raise ValueError("Users already exist. Cannot create initial admin.")

        return self.create_user(
            username=username,
            email=email,
            password=password,
            display_name="Administrator",
            role=UserRole.full_access(),
            created_by="system",
        )
