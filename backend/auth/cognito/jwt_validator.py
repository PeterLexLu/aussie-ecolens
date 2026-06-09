"""Cognito JWT validation for protected API requests."""

from __future__ import annotations

import base64
import functools
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal


COGNITO_REGION = os.getenv("COGNITO_REGION", "us-east-1")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "us-east-1_ahvGMB95O")
COGNITO_APP_CLIENT_ID = os.getenv("COGNITO_APP_CLIENT_ID", "2scr7btsqhli8d0hcchdltvnf5")
COGNITO_ISSUER = os.getenv(
    "COGNITO_ISSUER",
    f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}",
)
JWKS_URL = os.getenv("JWKS_URL", f"{COGNITO_ISSUER}/.well-known/jwks.json")


class AuthError(Exception):
    """Raised when an API request cannot be authenticated or authorised."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class CognitoClaims:
    """Claims required by the rest of the application."""

    owner_id: str
    email: str
    token_use: str
    raw_claims: dict[str, Any]


def _split_jwt(token: str) -> tuple[str, str, str]:
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("Invalid bearer token")
    return parts[0], parts[1], parts[2]


def _b64url_json(segment: str) -> dict[str, Any]:
    padded = segment + "=" * (-len(segment) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
        return json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthError("Invalid bearer token") from exc


def _b64url_bytes(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("utf-8"))
    except ValueError as exc:
        raise AuthError("Invalid bearer token") from exc


@functools.lru_cache(maxsize=1)
def fetch_jwks() -> dict[str, Any]:
    """Fetch and cache the Cognito JSON Web Key Set."""

    request = urllib.request.Request(JWKS_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_jwk(kid: str) -> dict[str, Any]:
    for key in fetch_jwks().get("keys", []):
        if key.get("kid") == kid:
            return key
    raise AuthError("Signing key not found")


def _verify_rs256_signature(token: str, jwk: dict[str, Any]) -> None:
    """Verify an RS256 JWT signature using the matching Cognito JWK.

    Direct backend verification needs the `cryptography` package. In the cloud
    deployment, API Gateway's Cognito/JWT authorizer can perform this step before
    the request reaches Lambda, and Lambda can read the verified claims.
    """

    try:
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from cryptography.hazmat.primitives.hashes import SHA256
    except ImportError as exc:
        raise AuthError("JWT signature verification dependency is missing") from exc

    header, payload, signature = _split_jwt(token)
    exponent = int.from_bytes(_b64url_bytes(jwk["e"]), "big")
    modulus = int.from_bytes(_b64url_bytes(jwk["n"]), "big")
    public_key = rsa.RSAPublicNumbers(exponent, modulus).public_key()
    signed = f"{header}.{payload}".encode("utf-8")
    try:
        public_key.verify(
            _b64url_bytes(signature),
            signed,
            padding.PKCS1v15(),
            SHA256(),
        )
    except Exception as exc:
        raise AuthError("Invalid token signature") from exc


def _validate_registered_claims(
    claims: dict[str, Any],
    expected_token_use: Literal["id", "access"] | None,
) -> None:
    if claims.get("iss") != COGNITO_ISSUER:
        raise AuthError("Invalid token issuer")

    token_use = claims.get("token_use")
    if expected_token_use and token_use != expected_token_use:
        raise AuthError("Invalid token use")

    audience = claims.get("aud") or claims.get("client_id")
    if audience != COGNITO_APP_CLIENT_ID:
        raise AuthError("Invalid token audience")

    timestamp = int(time.time())
    if int(claims.get("exp", 0)) <= timestamp:
        raise AuthError("Token has expired")
    if int(claims.get("nbf", 0) or 0) > timestamp:
        raise AuthError("Token is not active yet")


def validate_cognito_jwt(
    token: str,
    expected_token_use: Literal["id", "access"] | None = None,
    verify_signature: bool | None = None,
) -> CognitoClaims:
    """Validate a Cognito JWT and return the user context claims.

    `verify_signature` defaults to true unless API Gateway authorizer mode is
    enabled via `JWT_TRUST_API_GATEWAY=true`.
    """

    header_segment, payload_segment, _ = _split_jwt(token)
    header = _b64url_json(header_segment)
    claims = _b64url_json(payload_segment)

    _validate_registered_claims(claims, expected_token_use)
    should_verify_signature = verify_signature
    if should_verify_signature is None:
        should_verify_signature = os.getenv("JWT_TRUST_API_GATEWAY", "false").lower() != "true"
    if should_verify_signature:
        kid = header.get("kid")
        if not kid:
            raise AuthError("Token is missing signing key id")
        _verify_rs256_signature(token, _get_jwk(kid))

    owner_id = claims.get("sub")
    email = claims.get("email", "")
    if not owner_id:
        raise AuthError("Token is missing Cognito subject")
    return CognitoClaims(
        owner_id=owner_id,
        email=email,
        token_use=str(claims.get("token_use", "")),
        raw_claims=claims,
    )
