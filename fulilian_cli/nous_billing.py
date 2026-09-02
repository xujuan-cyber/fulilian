"""Nous Portal billing HTTP API client.

Provides the full billing API surface for the Nous Portal, including
exception types, request helpers, and all billing/subscription endpoints.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

# Re-export the stdlib module so tests can monkeypatch nb.urllib.request.urlopen
urllib = urllib.request

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class BillingError(Exception):
    """Base billing error with status, error, message, portal_url, actor, recovery."""

    def __init__(
        self,
        status: int,
        error: str,
        message: str = "",
        portal_url: str | None = None,
        actor: str | None = None,
        recovery: str | None = None,
        **extra: Any,
    ) -> None:
        self.status = status
        self.error = error
        self.message = message
        self.portal_url = portal_url
        self.actor = actor
        self.recovery = recovery
        for k, v in extra.items():
            setattr(self, k, v)
        super().__init__(f"[{status}] {error}: {message}")


class BillingAuthError(BillingError):
    """Authentication error (e.g. invalid/expired token)."""


class BillingScopeRequired(BillingError):
    """Insufficient OAuth scope for the requested operation."""


class BillingTransient(BillingError):
    """Transient server error (retryable)."""


class BillingRemoteSpendingRevoked(BillingError):
    """Remote spending has been revoked for this session."""


class BillingSessionRevoked(BillingError):
    """The session has been revoked (re-login required)."""


class BillingStripeUnavailable(BillingError):
    """Stripe payment processor is temporarily unavailable."""


class BillingUpgradeCapExceeded(BillingError):
    """Upgrade cap exceeded (e.g. monthly spend limit reached)."""


class BillingRateLimited(BillingError):
    """Rate limited by the server."""

    def __init__(
        self,
        status: int,
        error: str,
        message: str = "",
        portal_url: str | None = None,
        retry_after: int | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(status, error, message, portal_url, **extra)
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------

_token_cache: tuple[str, str] | None = None
"""Cached (token, base_url) pair from the last successful resolution."""


def invalidate_cached_token() -> None:
    """Clear the cached token so the next request re-resolves from auth."""
    global _token_cache
    _token_cache = None


# ---------------------------------------------------------------------------
# Portal URL resolution
# ---------------------------------------------------------------------------


def resolve_portal_base_url() -> str:
    """Return the portal base URL from the environment variable.

    Reads ``FULILIAN_PORTAL_BASE_URL``. Falls back to the production portal.
    """
    return (
        os.environ.get("FULILIAN_PORTAL_BASE_URL", "")
        or "https://portal.nousresearch.com"
    ).rstrip("/")


def _absolutize_portal_url(relative_url: str | None) -> str | None:
    """Resolve a relative portal URL against the active portal base.

    When ``relative_url`` is already absolute (starts with ``http://`` or
    ``https://``), return it unchanged. When it is ``None`` or empty, return
    ``None``. Otherwise, join it with the portal base URL from the environment.
    """
    if not relative_url:
        return None
    relative_url = relative_url.strip()
    if not relative_url:
        return None
    if relative_url.startswith(("http://", "https://")):
        return relative_url
    base = resolve_portal_base_url()
    return f"{base.rstrip('/')}/{relative_url.lstrip('/')}"


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def _resolve_token_and_base(**kw: Any) -> tuple[str, str]:
    """Resolve the Nous Portal access token and base URL.

    Keyword arguments:
        use_cache (bool): Whether to use the cached token (default ``True``).

    Returns a ``(token, base_url)`` tuple. Raises ``BillingAuthError`` when
    no token is available.
    """
    use_cache = kw.get("use_cache", True)

    global _token_cache
    if use_cache and _token_cache is not None:
        return _token_cache

    # Lazily import auth helpers to avoid circular imports at module load time.
    try:
        from fulilian_cli.auth import get_provider_auth_state, resolve_nous_access_token
    except Exception as exc:
        raise BillingAuthError(
            status=401,
            error="auth_unavailable",
            message=f"Could not load auth module: {exc}",
        ) from exc

    try:
        access_token = resolve_nous_access_token()
    except Exception as exc:
        raise BillingAuthError(
            status=401,
            error="token_resolution_failed",
            message=f"Failed to resolve Nous access token: {exc}",
        ) from exc

    if not isinstance(access_token, str) or not access_token.strip():
        raise BillingAuthError(
            status=401,
            error="no_token",
            message="No Nous Portal access token available. Log in with `fulilian model`.",
        )

    state = get_provider_auth_state("nous") or {}
    portal_base_url = state.get("portal_base_url")
    if not isinstance(portal_base_url, str) or not portal_base_url.strip():
        portal_base_url = resolve_portal_base_url()
    else:
        portal_base_url = portal_base_url.strip().rstrip("/")

    _token_cache = (access_token, portal_base_url)
    return access_token, portal_base_url


# ---------------------------------------------------------------------------
# HTTP error mapping
# ---------------------------------------------------------------------------


def _raise_for_error(
    status: int,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> None:
    """Map an HTTP error response to the appropriate ``BillingError`` subclass.

    Raises the mapped exception; never returns normally.
    """
    error = (payload.get("error") or "") if isinstance(payload, dict) else ""
    message = (payload.get("message") or "") if isinstance(payload, dict) else ""
    portal_url = _absolutize_portal_url(
        payload.get("portalUrl") if isinstance(payload, dict) else None
    )
    actor = payload.get("actor") if isinstance(payload, dict) else None
    recovery = payload.get("recovery") if isinstance(payload, dict) else None

    # Retry-After header → rate limited
    retry_after: int | None = None
    if headers and isinstance(headers, dict):
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is not None:
            try:
                retry_after = int(raw)
            except (ValueError, TypeError):
                pass

    # 4xx/5xx discriminator via status + error code
    if status == 401:
        if error == "session_revoked":
            raise BillingSessionRevoked(
                status, error, message, portal_url=portal_url, actor=actor, recovery=recovery
            )
        raise BillingAuthError(
            status, error, message, portal_url=portal_url, actor=actor, recovery=recovery
        )

    if status == 403:
        if error == "remote_spending_revoked":
            raise BillingRemoteSpendingRevoked(
                status, error, message, portal_url=portal_url, actor=actor, recovery=recovery
            )
        if error == "insufficient_scope":
            raise BillingScopeRequired(
                status, error, message, portal_url=portal_url, actor=actor, recovery=recovery
            )
        if error == "upgrade_cap_exceeded":
            raise BillingUpgradeCapExceeded(
                status, error, message, portal_url=portal_url, actor=actor, recovery=recovery
            )
        raise BillingError(
            status, error, message, portal_url=portal_url, actor=actor, recovery=recovery
        )

    if status == 429:
        raise BillingRateLimited(
            status,
            error or "rate_limited",
            message,
            portal_url=portal_url,
            retry_after=retry_after,
        )

    if status in (502, 503, 504):
        if error == "stripe_unavailable":
            raise BillingStripeUnavailable(
                status, error, message, portal_url=portal_url, actor=actor, recovery=recovery
            )
        raise BillingTransient(
            status, error or "temporarily_unavailable", message, portal_url=portal_url
        )

    # Generic fallback
    raise BillingError(status, error or "unknown", message, portal_url=portal_url)


# ---------------------------------------------------------------------------
# Core request helper
# ---------------------------------------------------------------------------


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 15,
    **kw: Any,
) -> dict[str, Any]:
    """Perform an authenticated HTTP request to the Nous Portal billing API.

    Automatically resolves the access token, sets ``Authorization`` and
    ``Content-Type`` headers, and maps errors via ``_raise_for_error``.
    On a 401 response, the token cache is invalidated and the request is
    retried once with a freshly resolved token.

    Returns the parsed JSON response body as a dict.
    """
    token, base_url = _resolve_token_and_base(**kw)
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            payload: dict[str, Any] = json.loads(raw)
            if not isinstance(payload, dict):
                return {}
            return payload
    except urllib.error.HTTPError as exc:
        status = exc.status
        raw_body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            payload = {"error": "non_json_response", "message": raw_body[:500]}

        # On 401, invalidate cache and retry once
        if status == 401:
            invalidate_cached_token()
            try:
                new_token, _ = _resolve_token_and_base(use_cache=False)
            except BillingAuthError:
                # Token refresh failed — raise the original error
                _raise_for_error(status, payload, dict(exc.headers or {}))
                raise  # unreachable

            headers["Authorization"] = f"Bearer {new_token}"
            retry_req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(retry_req, timeout=timeout) as retry_resp:
                    retry_raw = retry_resp.read().decode("utf-8")
                    retry_payload: dict[str, Any] = json.loads(retry_raw)
                    if not isinstance(retry_payload, dict):
                        return {}
                    return retry_payload
            except urllib.error.HTTPError as retry_exc:
                retry_body = retry_exc.read().decode("utf-8", errors="replace")
                try:
                    retry_payload = json.loads(retry_body)
                except (json.JSONDecodeError, ValueError):
                    retry_payload = {"error": "non_json_response", "message": retry_body[:500]}
                _raise_for_error(retry_exc.status, retry_payload, dict(retry_exc.headers or {}))
                raise  # unreachable

        # Non-401 error: map and raise
        _raise_for_error(status, payload, dict(exc.headers or {}))
        raise  # unreachable
    except urllib.error.URLError as exc:
        raise BillingError(
            status=0,
            error="connection_error",
            message=f"Failed to connect to billing API: {exc.reason}",
        ) from exc


# ---------------------------------------------------------------------------
# Billing API functions
# ---------------------------------------------------------------------------


def get_billing_state(timeout: float = 15) -> dict[str, Any]:
    """GET the current billing state from the portal.

    Returns the parsed JSON response body.
    """
    return _request("GET", "/api/billing/state", timeout=timeout)


def get_subscription_state(timeout: float = 15) -> dict[str, Any]:
    """GET the current subscription state from the portal.

    Returns the parsed JSON response body.
    """
    return _request("GET", "/api/billing/subscription", timeout=timeout)


def get_charge_status(charge_id: str) -> dict[str, Any]:
    """GET the status of a specific charge by its ID.

    Args:
        charge_id: The charge identifier returned by ``post_charge``.

    Returns the parsed JSON response body.
    """
    return _request("GET", f"/api/billing/charge/{charge_id}")


def post_subscription_preview(subscription_type_id: str) -> dict[str, Any]:
    """POST a subscription preview for a given tier.

    Args:
        subscription_type_id: The tier/plan identifier.

    Returns the preview data (pricing, credits, etc.).
    """
    return _request(
        "POST",
        "/api/billing/subscription/preview",
        body={"subscriptionTypeId": subscription_type_id},
    )


def put_subscription_pending_change(
    subscription_type_id: str, cancel: bool = False
) -> dict[str, Any]:
    """PUT (set) a pending subscription change.

    Args:
        subscription_type_id: The target tier/plan identifier.
        cancel: If ``True``, cancel the pending change instead.

    Returns the updated subscription state.
    """
    return _request(
        "PUT",
        "/api/billing/subscription/pending-change",
        body={"subscriptionTypeId": subscription_type_id, "cancel": cancel},
    )


def delete_subscription_pending_change() -> dict[str, Any]:
    """DELETE the pending subscription change (revert to current plan).

    Returns the updated subscription state.
    """
    return _request("DELETE", "/api/billing/subscription/pending-change")


def post_subscription_upgrade(
    subscription_type_id: str, idempotency_key: str
) -> dict[str, Any]:
    """POST an immediate subscription upgrade.

    Args:
        subscription_type_id: The target tier/plan identifier.
        idempotency_key: Unique key for idempotency (prevents duplicate charges).

    Returns the updated subscription state.
    """
    return _request(
        "POST",
        "/api/billing/subscription/upgrade",
        body={
            "subscriptionTypeId": subscription_type_id,
            "idempotencyKey": idempotency_key,
        },
    )


def post_charge(amount_usd: float, idempotency_key: str) -> dict[str, Any]:
    """POST a one-time top-up charge.

    Args:
        amount_usd: The dollar amount to charge.
        idempotency_key: Unique key for idempotency (prevents duplicate charges).

    Returns the charge result including ``chargeId``.
    """
    return _request(
        "POST",
        "/api/billing/charge",
        body={"amountUsd": amount_usd, "idempotencyKey": idempotency_key},
    )


def patch_auto_top_up(
    enabled: bool,
    threshold: float | None = None,
    top_up_amount: float | None = None,
) -> dict[str, Any]:
    """PATCH the auto top-up configuration.

    Args:
        enabled: Whether auto top-up is enabled.
        threshold: The balance threshold that triggers a top-up (in USD).
        top_up_amount: The amount to top up (in USD).

    Returns the updated auto top-up configuration.
    """
    body: dict[str, Any] = {"enabled": enabled}
    if threshold is not None:
        body["thresholdUsd"] = threshold
    if top_up_amount is not None:
        body["topUpAmountUsd"] = top_up_amount
    return _request("PATCH", "/api/billing/auto-top-up", body=body)


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    # Exceptions
    "BillingError",
    "BillingAuthError",
    "BillingScopeRequired",
    "BillingTransient",
    "BillingRemoteSpendingRevoked",
    "BillingSessionRevoked",
    "BillingStripeUnavailable",
    "BillingUpgradeCapExceeded",
    "BillingRateLimited",
    # URL resolution
    "resolve_portal_base_url",
    "_absolutize_portal_url",
    "_resolve_token_and_base",
    # HTTP error mapping
    "_raise_for_error",
    # Token cache
    "invalidate_cached_token",
    "_token_cache",
    # Billing API functions
    "get_billing_state",
    "get_subscription_state",
    "get_charge_status",
    "post_subscription_preview",
    "put_subscription_pending_change",
    "delete_subscription_pending_change",
    "post_subscription_upgrade",
    "post_charge",
    "patch_auto_top_up",
    # Re-export stdlib for testing fakes
    "urllib",
]