"""Persistent user / role management for the AISE web console.

This module replaces the previous session-only, env-var-configured
admin with a proper, persistent user store:

- Users are stored in ``<projects_root>/users.json``.
- Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib only — no
  dependency on passlib/bcrypt). Each password uses its own salt.
- Roles are predefined (super_admin / admin / developer / viewer) and
  encode a set of permissions. Users are tagged with ONE role.
- A bootstrap super_admin is created on first start from the env vars
  ``AISE_ADMIN_USERNAME`` and ``AISE_ADMIN_PASSWORD`` (same variables
  the legacy local-login used) so existing operators don't lose
  access. If the store already has a super_admin, the env-var bootstrap
  is skipped — manual user changes win.

The store is thread-safe via an internal ``RLock``.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import pbkdf2_hmac
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger

logger = get_logger(__name__)

# Predefined permission keys. Kept flat so frontend code can present a
# simple "role → permissions" matrix without tree-walking.
PERM_MANAGE_USERS = "manage_users"
PERM_MANAGE_SYSTEM = "manage_system"  # global config, agents, models
PERM_VIEW_LOGS = "view_logs"
PERM_ANALYZE_LOGS = "analyze_logs"
PERM_MANAGE_PROJECTS = "manage_projects"  # create / delete projects
PERM_RUN_PROJECTS = "run_projects"  # submit requirements, restart runs
PERM_VIEW_PROJECTS = "view_projects"

ALL_PERMISSIONS: tuple[str, ...] = (
    PERM_MANAGE_USERS,
    PERM_MANAGE_SYSTEM,
    PERM_VIEW_LOGS,
    PERM_ANALYZE_LOGS,
    PERM_MANAGE_PROJECTS,
    PERM_RUN_PROJECTS,
    PERM_VIEW_PROJECTS,
)

# Built-in roles. Users can be assigned one of these. Intentionally
# small — a 4-role matrix is enough to cover the console's real needs
# (full admin, project admin, developer, read-only viewer). Roles are
# hard-coded rather than dynamic because the UI surfaces them in
# dropdowns / permission matrices and a dynamic role model would drag
# in a whole RBAC editor screen that nobody asked for.
ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "super_admin": {
        "display_name_zh": "超级管理员",
        "display_name_en": "Super Admin",
        "description_zh": "拥有所有权限，包含用户管理、系统配置、日志查看、日志分析、项目管理等。",
        "description_en": "Full access — user management, system config, logs, analysis, projects.",
        "permissions": list(ALL_PERMISSIONS),
    },
    "admin": {
        "display_name_zh": "管理员",
        "display_name_en": "Admin",
        "description_zh": "系统配置、项目管理、日志查看及分析，不能管理用户。",
        "description_en": "System config, project management, logs, analysis. Cannot manage users.",
        "permissions": [
            PERM_MANAGE_SYSTEM,
            PERM_VIEW_LOGS,
            PERM_ANALYZE_LOGS,
            PERM_MANAGE_PROJECTS,
            PERM_RUN_PROJECTS,
            PERM_VIEW_PROJECTS,
        ],
    },
    "developer": {
        "display_name_zh": "开发人员",
        "display_name_en": "Developer",
        "description_zh": "创建项目、下发需求，查看日志，不能管理用户或修改全局配置。",
        "description_en": "Create/run projects, view logs. No user management or system config.",
        "permissions": [
            PERM_VIEW_LOGS,
            PERM_MANAGE_PROJECTS,
            PERM_RUN_PROJECTS,
            PERM_VIEW_PROJECTS,
        ],
    },
    "viewer": {
        "display_name_zh": "只读访客",
        "display_name_en": "Viewer",
        "description_zh": "仅能查看项目和执行记录。",
        "description_en": "Read-only access to projects and runs.",
        "permissions": [PERM_VIEW_PROJECTS],
    },
}


_PBKDF2_ITERATIONS = 260_000
_PBKDF2_HASH = "sha256"


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256.

    Returns a compact ``pbkdf2_sha256$<iter>$<hex_salt>$<hex_hash>``
    string so the format is self-describing and can later be migrated
    to bcrypt / argon2 without breaking existing records.
    """
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = pbkdf2_hmac(_PBKDF2_HASH, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification against a stored ``pbkdf2_sha256$…`` hash."""
    try:
        algo, iter_str, salt_hex, digest_hex = encoded.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    computed = pbkdf2_hmac(_PBKDF2_HASH, password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(computed, expected)


@dataclass
class User:
    """A stored user record."""

    id: str
    username: str
    email: str
    display_name: str
    role: str
    enabled: bool
    password_hash: str
    provider: str  # "local" / "google" / "microsoft" etc.
    created_at: str
    updated_at: str
    last_login_at: str = ""
    # External identity id for OAuth users (sub claim). Empty for local.
    external_id: str = ""
    notes: str = ""

    def to_dict(self, *, include_password_hash: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "enabled": self.enabled,
            "provider": self.provider,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_login_at": self.last_login_at,
            "external_id": self.external_id,
            "notes": self.notes,
        }
        if include_password_hash:
            data["password_hash"] = self.password_hash
        return data


@dataclass
class _StoreState:
    users: dict[str, User] = field(default_factory=dict)

    def by_username(self, username: str) -> User | None:
        lookup = username.strip().lower()
        for u in self.users.values():
            if u.username.lower() == lookup:
                return u
        return None

    def by_email(self, email: str) -> User | None:
        lookup = email.strip().lower()
        if not lookup:
            return None
        for u in self.users.values():
            if u.email.lower() == lookup:
                return u
        return None


class UserStore:
    """Thread-safe JSON-backed user store."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._state = _StoreState()
        self._lock = threading.RLock()
        self._load()
        self._bootstrap_admin_if_empty()

    # -- Role helpers --------------------------------------------------------

    @staticmethod
    def role_exists(role: str) -> bool:
        return role in ROLE_DEFINITIONS

    @staticmethod
    def permissions_for(role: str) -> list[str]:
        defn = ROLE_DEFINITIONS.get(role)
        if not defn:
            return []
        return list(defn.get("permissions", []))

    @staticmethod
    def list_role_definitions() -> list[dict[str, Any]]:
        return [
            {
                "key": key,
                "display_name_zh": defn["display_name_zh"],
                "display_name_en": defn["display_name_en"],
                "description_zh": defn["description_zh"],
                "description_en": defn["description_en"],
                "permissions": list(defn["permissions"]),
            }
            for key, defn in ROLE_DEFINITIONS.items()
        ]

    @staticmethod
    def list_all_permissions() -> list[str]:
        return list(ALL_PERMISSIONS)

    # -- Persistence ---------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load user store %s: %s", self._path, exc)
            return
        if not isinstance(data, dict):
            return
        users_data = data.get("users", [])
        if not isinstance(users_data, list):
            return
        for entry in users_data:
            if not isinstance(entry, dict):
                continue
            user_id = str(entry.get("id", "")).strip()
            username = str(entry.get("username", "")).strip()
            if not user_id or not username:
                continue
            role = str(entry.get("role", "viewer"))
            if role not in ROLE_DEFINITIONS:
                role = "viewer"
            self._state.users[user_id] = User(
                id=user_id,
                username=username,
                email=str(entry.get("email", "")),
                display_name=str(entry.get("display_name", username)),
                role=role,
                enabled=bool(entry.get("enabled", True)),
                password_hash=str(entry.get("password_hash", "")),
                provider=str(entry.get("provider", "local")),
                created_at=str(entry.get("created_at", _now_iso())),
                updated_at=str(entry.get("updated_at", _now_iso())),
                last_login_at=str(entry.get("last_login_at", "")),
                external_id=str(entry.get("external_id", "")),
                notes=str(entry.get("notes", "")),
            )

    def _save_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "users": [u.to_dict(include_password_hash=True) for u in self._state.users.values()],
        }
        tmp = self._path.with_suffix(f"{self._path.suffix}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def _bootstrap_admin_if_empty(self) -> None:
        """Create an initial super_admin if the store has no super_admin yet.

        Uses ``AISE_ADMIN_USERNAME`` / ``AISE_ADMIN_PASSWORD`` so legacy
        operators can keep logging in. Falls back to ``admin`` /
        ``123456`` (same defaults as the old local-login hardcode).
        """
        with self._lock:
            for u in self._state.users.values():
                if u.role == "super_admin" and u.enabled:
                    return
            username = (os.environ.get("AISE_ADMIN_USERNAME") or "admin").strip() or "admin"
            password = os.environ.get("AISE_ADMIN_PASSWORD") or "123456"
            now = _now_iso()
            existing = self._state.by_username(username)
            if existing is not None:
                existing.role = "super_admin"
                existing.enabled = True
                existing.updated_at = now
            else:
                user = User(
                    id=f"u_{uuid.uuid4().hex[:10]}",
                    username=username,
                    email=f"{username}@aise.local",
                    display_name="System Admin",
                    role="super_admin",
                    enabled=True,
                    password_hash=hash_password(password),
                    provider="local",
                    created_at=now,
                    updated_at=now,
                )
                self._state.users[user.id] = user
            try:
                self._save_locked()
            except Exception as exc:
                logger.warning("Failed to persist bootstrap admin: %s", exc)
            logger.info("Bootstrap super_admin ensured: username=%s", username)

    # -- CRUD ----------------------------------------------------------------

    def list_users(self) -> list[User]:
        with self._lock:
            items = list(self._state.users.values())
        items.sort(key=lambda u: (u.role != "super_admin", u.username.lower()))
        return items

    def get_user(self, user_id: str) -> User | None:
        with self._lock:
            return self._state.users.get(user_id)

    def get_user_by_username(self, username: str) -> User | None:
        with self._lock:
            return self._state.by_username(username)

    def get_user_by_external(self, provider: str, external_id: str, email: str = "") -> User | None:
        """Match an OAuth callback to a stored user.

        Tries ``(provider, external_id)`` first, then falls back to
        matching by email so returning OAuth users don't get duplicated
        just because the external ID changed format.
        """
        provider = provider.strip().lower()
        external_id = external_id.strip()
        email = email.strip().lower()
        with self._lock:
            for u in self._state.users.values():
                if u.provider.lower() == provider and external_id and u.external_id == external_id:
                    return u
            if email:
                for u in self._state.users.values():
                    if u.email.lower() == email:
                        return u
        return None

    def create_user(
        self,
        *,
        username: str,
        email: str,
        display_name: str,
        role: str,
        password: str,
        enabled: bool = True,
        provider: str = "local",
        external_id: str = "",
        notes: str = "",
    ) -> User:
        username = username.strip()
        if not username:
            raise ValueError("username is required")
        if role not in ROLE_DEFINITIONS:
            raise ValueError(f"Unknown role: {role}")
        if provider == "local" and not password:
            raise ValueError("password is required for local users")
        with self._lock:
            if self._state.by_username(username) is not None:
                raise ValueError(f"Username already exists: {username}")
            if email and self._state.by_email(email) is not None:
                raise ValueError(f"Email already exists: {email}")
            now = _now_iso()
            user = User(
                id=f"u_{uuid.uuid4().hex[:10]}",
                username=username,
                email=email.strip(),
                display_name=(display_name.strip() or username),
                role=role,
                enabled=enabled,
                password_hash=hash_password(password) if password else "",
                provider=provider.strip() or "local",
                created_at=now,
                updated_at=now,
                external_id=external_id.strip(),
                notes=notes.strip(),
            )
            self._state.users[user.id] = user
            self._save_locked()
            logger.info("User created: id=%s username=%s role=%s", user.id, user.username, user.role)
            return user

    def update_user(
        self,
        user_id: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
        role: str | None = None,
        enabled: bool | None = None,
        notes: str | None = None,
        external_id: str | None = None,
    ) -> User:
        with self._lock:
            user = self._state.users.get(user_id)
            if user is None:
                raise ValueError(f"User not found: {user_id}")
            if role is not None:
                if role not in ROLE_DEFINITIONS:
                    raise ValueError(f"Unknown role: {role}")
                if user.role == "super_admin" and role != "super_admin":
                    # Prevent orphaning — leave at least one super_admin.
                    other_admins = [
                        u
                        for u in self._state.users.values()
                        if u.id != user.id and u.role == "super_admin" and u.enabled
                    ]
                    if not other_admins:
                        raise ValueError("Cannot demote the last super_admin")
                user.role = role
            if email is not None:
                new_email = email.strip()
                if new_email and new_email.lower() != user.email.lower():
                    existing = self._state.by_email(new_email)
                    if existing and existing.id != user.id:
                        raise ValueError(f"Email already exists: {new_email}")
                user.email = new_email
            if display_name is not None:
                user.display_name = display_name.strip() or user.username
            if enabled is not None:
                if not enabled and user.role == "super_admin":
                    other_admins = [
                        u
                        for u in self._state.users.values()
                        if u.id != user.id and u.role == "super_admin" and u.enabled
                    ]
                    if not other_admins:
                        raise ValueError("Cannot disable the last super_admin")
                user.enabled = enabled
            if notes is not None:
                user.notes = notes
            if external_id is not None:
                user.external_id = external_id.strip()
            user.updated_at = _now_iso()
            self._save_locked()
            logger.info("User updated: id=%s", user.id)
            return user

    def set_password(self, user_id: str, password: str) -> None:
        if not password:
            raise ValueError("password is required")
        with self._lock:
            user = self._state.users.get(user_id)
            if user is None:
                raise ValueError(f"User not found: {user_id}")
            user.password_hash = hash_password(password)
            user.updated_at = _now_iso()
            self._save_locked()
            logger.info("Password set: id=%s", user.id)

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            user = self._state.users.get(user_id)
            if user is None:
                raise ValueError(f"User not found: {user_id}")
            if user.role == "super_admin":
                other_admins = [
                    u
                    for u in self._state.users.values()
                    if u.id != user.id and u.role == "super_admin" and u.enabled
                ]
                if not other_admins:
                    raise ValueError("Cannot delete the last super_admin")
            del self._state.users[user_id]
            self._save_locked()
            logger.info("User deleted: id=%s username=%s", user_id, user.username)

    def authenticate(self, username: str, password: str) -> User | None:
        with self._lock:
            user = self._state.by_username(username)
            if user is None or not user.enabled or user.provider != "local":
                return None
            if not verify_password(password, user.password_hash):
                return None
            user.last_login_at = _now_iso()
            try:
                self._save_locked()
            except Exception as exc:
                logger.debug("Failed to persist last_login_at: %s", exc)
            return user

    def record_external_login(
        self,
        *,
        provider: str,
        external_id: str,
        email: str,
        display_name: str,
    ) -> User:
        """Upsert a user from an OAuth callback.

        Returns the stored User record (existing or newly created). The
        caller passes the result into ``session_payload`` to build the
        session dict.
        """
        provider = provider.strip() or "local"
        email = email.strip()
        display_name = display_name.strip() or email or provider
        with self._lock:
            user = self.get_user_by_external(provider, external_id, email)
            if user is not None:
                user.provider = provider
                if email and user.email.lower() != email.lower():
                    user.email = email
                if display_name and display_name != user.display_name:
                    user.display_name = display_name
                if external_id:
                    user.external_id = external_id
                user.enabled = True
                user.last_login_at = _now_iso()
                user.updated_at = _now_iso()
                self._save_locked()
                return user
            # First-time OAuth user. Default role is ``viewer`` — admins
            # promote them via the user management UI.
            username_base = (email.split("@")[0] if email else provider).strip() or provider
            username = username_base
            suffix = 1
            while self._state.by_username(username) is not None:
                suffix += 1
                username = f"{username_base}{suffix}"
            now = _now_iso()
            user = User(
                id=f"u_{uuid.uuid4().hex[:10]}",
                username=username,
                email=email,
                display_name=display_name,
                role="viewer",
                enabled=True,
                password_hash="",
                provider=provider,
                created_at=now,
                updated_at=now,
                last_login_at=now,
                external_id=external_id,
            )
            self._state.users[user.id] = user
            self._save_locked()
            logger.info("OAuth user created: id=%s username=%s provider=%s", user.id, user.username, provider)
            return user


def session_payload(user: User) -> dict[str, Any]:
    """Build the ``request.session['user']`` dict for a given User.

    Embeds ``permissions`` so route handlers can gate on them without
    re-reading the store on every request.
    """
    return {
        "id": user.id,
        "name": user.display_name or user.username,
        "username": user.username,
        "email": user.email,
        "provider": user.provider,
        "role": user.role,
        "permissions": UserStore.permissions_for(user.role),
    }


def has_permission(session_user: dict[str, Any] | None, permission: str) -> bool:
    if not session_user:
        return False
    perms = session_user.get("permissions") or []
    if permission in perms:
        return True
    # super_admin gets everything even if perms list is stale.
    return session_user.get("role") == "super_admin"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
