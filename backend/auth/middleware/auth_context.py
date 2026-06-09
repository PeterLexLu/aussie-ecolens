"""Protected route and user-context helpers."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from functools import wraps
from typing import Any, Callable

from backend.auth.cognito.jwt_validator import AuthError, validate_cognito_jwt


@dataclass(frozen=True)
class UserContext:
    """User identity passed to storage, database, query, and notification code."""

    owner_id: str
    email: str

    def to_api_dict(self) -> dict[str, str]:
        return asdict(self)


def error_response(message: str, status_code: int = 400) -> dict[str, Any]:
    """Shared API error shape for all protected routes."""

    return {
        "statusCode": status_code,
        "body": {"error": message},
    }


def get_bearer_token(headers: dict[str, str] | None) -> str | None:
    """Extract Authorization: Bearer <token> from request headers."""

    if not headers:
        return None
    authorization = headers.get("Authorization") or headers.get("authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_mock_user_context() -> UserContext:
    """Local fallback user for early integration before Cognito is wired."""

    return UserContext(
        owner_id=os.getenv("MOCK_OWNER_ID", "demo-user"),
        email=os.getenv("MOCK_EMAIL", "demo@example.com"),
    )


def require_owner(user_context: UserContext, resource_owner_id: str) -> None:
    """Raise 403 when a user tries to modify another user's resource."""

    if user_context.owner_id != resource_owner_id:
        raise AuthError("Forbidden: resource belongs to another user", 403)


def owner_scoped_request(event: dict[str, Any], user_context: UserContext) -> dict[str, Any]:
    """Copy a request and attach the trusted owner id for data-layer filters."""

    scoped_event = dict(event)
    scoped_event["ownerId"] = user_context.owner_id
    return scoped_event


def get_user_context(event: dict[str, Any]) -> UserContext:
    """Build a user context from mock mode, API Gateway claims, or JWT."""

    if os.getenv("AUTH_MODE", "cognito") == "mock":
        return get_mock_user_context()

    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims")
    )
    if not claims:
        claims = event.get("requestContext", {}).get("authorizer", {}).get("claims")
    if claims:
        owner_id = claims.get("sub")
        if not owner_id:
            raise AuthError("Token is missing Cognito subject")
        return UserContext(owner_id=owner_id, email=claims.get("email", ""))

    token = get_bearer_token(event.get("headers"))
    if not token:
        raise AuthError("Authentication required")
    validated = validate_cognito_jwt(token, expected_token_use=None)
    return UserContext(owner_id=validated.owner_id, email=validated.email)


def require_auth(handler: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Wrap a route handler and inject user_context as a keyword argument."""

    @wraps(handler)
    def wrapper(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
        try:
            user_context = get_user_context(event)
            return handler(event, context, user_context=user_context)
        except AuthError as exc:
            return error_response(exc.message, exc.status_code)

    return wrapper
