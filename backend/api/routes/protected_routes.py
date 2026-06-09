"""Protected route registry for API Gateway and backend route guards."""

from __future__ import annotations


PUBLIC_ROUTES = {
    "POST /api/auth/signup",
    "POST /api/auth/login",
    "POST /api/auth/cognito/exchange",
    "GET /api/config",
}


PROTECTED_ROUTES = {
    "GET /api/me",
    "POST /api/uploads/init",
    "POST /api/upload",
    "GET /api/files",
    "GET /api/files/{fileId}",
    "POST /api/query/tags",
    "POST /api/query/species",
    "POST /api/query/thumbnail",
    "POST /api/query/by-file",
    "POST /api/tags/bulk",
    "POST /api/files/delete",
    "POST /api/subscribe",
    "GET /api/notifications",
}


def is_protected_route(method: str, path_template: str) -> bool:
    """Return whether a route must require Cognito authentication."""

    route_key = f"{method.upper()} {path_template}"
    return route_key in PROTECTED_ROUTES


def assert_route_is_protected(method: str, path_template: str) -> None:
    """Fail fast if a route that must be private is not in the registry."""

    if not is_protected_route(method, path_template):
        raise AssertionError(f"{method.upper()} {path_template} is not protected")
