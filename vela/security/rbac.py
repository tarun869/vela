"""Role-based access control: permissions, roles, and policy enforcement."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# --- Permission strings (resource:action) ---
PERMISSIONS = {
    # Assets
    "assets:read": "View asset list and details",
    "assets:write": "Create and update assets",
    "assets:delete": "Decommission assets",
    # Dispatch
    "dispatch:read": "View dispatch plans",
    "dispatch:write": "Submit dispatch optimization requests",
    "dispatch:approve": "Approve or reject dispatch plans",
    # Forecasts
    "forecasts:read": "View price and load forecasts",
    "forecasts:write": "Trigger forecast generation",
    # Market
    "market:read": "View market bids and prices",
    "market:write": "Create and submit market bids",
    # Settlements
    "settlements:read": "View settlement statements",
    "settlements:write": "Run settlement reconciliation",
    "settlements:finalize": "Finalize settlement statements",
    # Admin
    "admin:read": "View user and config data",
    "admin:write": "Manage users and system config",
    "admin:audit": "View audit logs",
    # Carbon
    "carbon:read": "View carbon metrics",
    # Analytics
    "analytics:read": "View analytics and KPIs",
}

# --- Role definitions ---
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "viewer": {
        "assets:read",
        "dispatch:read",
        "forecasts:read",
        "market:read",
        "settlements:read",
        "carbon:read",
        "analytics:read",
    },
    "operator": {
        "assets:read", "assets:write",
        "dispatch:read", "dispatch:write",
        "forecasts:read", "forecasts:write",
        "market:read", "market:write",
        "settlements:read",
        "carbon:read",
        "analytics:read",
    },
    "trader": {
        "assets:read",
        "dispatch:read",
        "forecasts:read",
        "market:read", "market:write",
        "settlements:read",
        "analytics:read",
    },
    "manager": {
        *PERMISSIONS.keys(),  # all permissions except admin:write
    } - {"admin:write"},
    "admin": set(PERMISSIONS.keys()),  # all permissions
}


@dataclass
class RBACPolicy:
    """Enforces role-based access for a given set of user roles."""
    roles: list[str]
    _effective_permissions: set[str] = field(init=False)

    def __post_init__(self) -> None:
        self._effective_permissions = set()
        for role in self.roles:
            self._effective_permissions.update(ROLE_PERMISSIONS.get(role, set()))

    def can(self, permission: str) -> bool:
        return permission in self._effective_permissions

    def require(self, permission: str) -> None:
        """Raise PermissionError if the permission is not granted."""
        if not self.can(permission):
            raise PermissionError(
                f"Permission denied: '{permission}' requires one of {_roles_with_permission(permission)}"
            )

    def permissions(self) -> set[str]:
        return set(self._effective_permissions)


def _roles_with_permission(permission: str) -> list[str]:
    return [role for role, perms in ROLE_PERMISSIONS.items() if permission in perms]


def require_permission(permission: str) -> Callable:
    """FastAPI dependency factory for permission-based access control."""
    from fastapi import Depends, HTTPException, status
    from vela.api.dependencies import CurrentUser

    async def _check(user: CurrentUser):
        policy = RBACPolicy(roles=user.roles)
        if not policy.can(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required",
            )
        return user

    return Depends(_check)
