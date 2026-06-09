"""Cognito runtime settings shared by backend auth modules."""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass


@dataclass(frozen=True)
class CognitoSettings:
    region: str
    user_pool_id: str
    app_client_id: str
    domain: str
    redirect_uri: str
    issuer: str
    jwks_url: str


def load_cognito_settings() -> CognitoSettings:
    region = os.getenv("COGNITO_REGION", "us-east-1")
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID", "us-east-1_ahvGMB95O")
    issuer = os.getenv(
        "COGNITO_ISSUER",
        f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}",
    )
    return CognitoSettings(
        region=region,
        user_pool_id=user_pool_id,
        app_client_id=os.getenv("COGNITO_APP_CLIENT_ID", "2scr7btsqhli8d0hcchdltvnf5"),
        domain=os.getenv("COGNITO_DOMAIN", "us-east-1ahvgmb95o.auth.us-east-1.amazoncognito.com"),
        redirect_uri=os.getenv("COGNITO_REDIRECT_URI", "http://localhost:8000/"),
        issuer=issuer,
        jwks_url=os.getenv("JWKS_URL", f"{issuer}/.well-known/jwks.json"),
    )


def build_hosted_ui_login_url(settings: CognitoSettings | None = None) -> str:
    cognito = settings or load_cognito_settings()
    query = urllib.parse.urlencode(
        {
            "client_id": cognito.app_client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": cognito.redirect_uri,
        }
    )
    return f"https://{cognito.domain}/login?{query}"
