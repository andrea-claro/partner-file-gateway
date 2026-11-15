"""Minimal SFTPGo REST API client (admin API, /api/v2)."""

from __future__ import annotations

from typing import Any

import httpx


class SftpGoError(RuntimeError):
    pass


class SftpGoClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not username or not password:
            raise SftpGoError("SFTPGO_ADMIN_USERNAME and SFTPGO_ADMIN_PASSWORD must be set")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v2", timeout=timeout, transport=transport
        )
        self._credentials = (username, password)
        self._token: str | None = None

    def _authenticate(self) -> str:
        response = self._http.get("/token", auth=self._credentials)
        _raise_for_status(response, "authenticate")
        self._token = response.json()["access_token"]
        return self._token

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = self._token or self._authenticate()
        response = self._http.request(
            method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        if response.status_code == httpx.codes.UNAUTHORIZED:  # token expired: retry once
            token = self._authenticate()
            response = self._http.request(
                method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
        return response

    def get_user(self, username: str) -> dict[str, Any] | None:
        response = self._request("GET", f"/users/{username}")
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        _raise_for_status(response, f"get user {username}")
        return response.json()

    def delete_user(self, username: str) -> bool:
        """Delete a user; returns False if it did not exist."""
        response = self._request("DELETE", f"/users/{username}")
        if response.status_code == httpx.codes.NOT_FOUND:
            return False
        _raise_for_status(response, f"delete user {username}")
        return True

    def upsert_user(self, user: dict[str, Any]) -> str:
        """Create the user, or replace its settings and drop its open sessions."""
        username = user["username"]
        if self.get_user(username) is None:
            response = self._request("POST", "/users", json=user)
            _raise_for_status(response, f"create user {username}")
            return "created"
        response = self._request("PUT", f"/users/{username}", params={"disconnect": 1}, json=user)
        _raise_for_status(response, f"update user {username}")
        return "updated"


def _raise_for_status(response: httpx.Response, action: str) -> None:
    if response.is_success:
        return
    try:
        detail = response.json().get("error") or response.json().get("message")
    except ValueError:
        detail = response.text[:200]
    raise SftpGoError(f"SFTPGo: cannot {action}: HTTP {response.status_code}: {detail}")
