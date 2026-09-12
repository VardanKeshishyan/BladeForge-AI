import asyncio
import json
import time
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from app.core.config import Settings


class TokenVerificationError(Exception):
    pass


class JWKSVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._keys: dict[str, Any] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        if not self.settings.supabase_jwks_url:
            return
        async with self._lock:
            if self._keys and self._expires_at > time.monotonic():
                return
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(self.settings.supabase_jwks_url)
                    response.raise_for_status()
                payload = response.json()
                self._keys = {
                    item["kid"]: RSAAlgorithm.from_jwk(json.dumps(item))
                    for item in payload.get("keys", [])
                    if item.get("kid")
                }
                self._expires_at = time.monotonic() + 600
            except (httpx.HTTPError, ValueError, KeyError):
                pass

    async def verify(self, token: str) -> dict[str, Any]:
        if self.settings.supabase_jwt_secret:
            try:
                claims = jwt.decode(
                    token,
                    key=self.settings.supabase_jwt_secret,
                    algorithms=["HS256"],
                    audience=self.settings.supabase_jwt_audience,
                    options={"require": ["exp", "iat", "sub"]},
                )
                return dict(claims)
            except jwt.PyJWTError:
                pass

        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if kid and self.settings.supabase_jwks_url:
                if kid not in self._keys or self._expires_at <= time.monotonic():
                    await self._refresh()
                key = self._keys.get(kid)
                if key is None:
                    self._expires_at = 0
                    await self._refresh()
                    key = self._keys.get(kid)
                if key is not None:
                    claims = jwt.decode(
                        token,
                        key=key,
                        algorithms=["RS256", "ES256"],
                        audience=self.settings.supabase_jwt_audience,
                        issuer=self.settings.supabase_jwt_issuer,
                        options={"require": ["exp", "iat", "sub"]},
                    )
                    return dict(claims)
        except (jwt.PyJWTError, httpx.HTTPError, ValueError):
            pass

        raise TokenVerificationError("Invalid or expired access token")

