"""
Server-side identity → ACL groups. Never trust user_groups from the client body.

Demo auth: `X-User-Id` header (or Streamlit sidebar identity). In production replace with
a verified JWT / gateway that sets groups after authentication.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from . import settings


def groups_for_user(user_id: str | None) -> list[str]:
    uid = (user_id or "guest").strip().lower() or "guest"
    groups = settings.IDENTITY_MAP.get(uid)
    if groups is None:
        # Unknown users get the public ACL only — never invent elevated groups.
        return ["public"]
    return list(groups)


def require_user(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> tuple[str, list[str]]:
    uid = (x_user_id or "guest").strip().lower() or "guest"
    return uid, groups_for_user(uid)


def require_reviewer(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> tuple[str, list[str]]:
    uid, groups = require_user(x_user_id)
    if "security" not in groups and "procurement" not in groups:
        raise HTTPException(403, "Approvers need security or procurement membership (set X-User-Id).")
    return uid, groups
