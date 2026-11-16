"""Data for the balance display and the refresh buttons (used by ``routes``).

Never returns or logs a key; only numbers and error messages.
"""

import os

from . import models as model_list
from .client import OpenRouterClient, OpenRouterError


def _env_client(name):
    key = os.environ.get(name, "").strip()
    return OpenRouterClient(key, timeout=20, retries=0) if key else None


def balance_payload(client=None, management_client=None):
    """``{"key": {...} | None, "credits": {...} | None, "errors": [...]}``.

    ``key``: ``limit``, ``limit_remaining`` (None = no limit), ``usage`` from ``GET /key``.
    ``credits``: ``total_credits``, ``total_usage``, ``remaining`` from ``GET /credits``,
    only when ``OPENROUTER_MANAGEMENT_KEY`` is set.
    """
    if client is None:
        client = _env_client("OPENROUTER_API_KEY")
    if management_client is None:
        management_client = _env_client("OPENROUTER_MANAGEMENT_KEY")

    out = {"key": None, "credits": None, "errors": []}
    if client is None:
        out["errors"].append("OPENROUTER_API_KEY is not set")
    else:
        try:
            info = client.key_status()
            out["key"] = {k: info.get(k) for k in ("limit", "limit_remaining", "usage")}
        except OpenRouterError as exc:
            out["errors"].append(f"key: {exc}")

    if management_client is not None:
        try:
            data = management_client.credits()
            total, used = data.get("total_credits"), data.get("total_usage")
            remaining = total - used if isinstance(total, (int, float)) and \
                isinstance(used, (int, float)) else None
            out["credits"] = {"total_credits": total, "total_usage": used,
                              "remaining": remaining}
        except OpenRouterError as exc:
            out["errors"].append(f"credits: {exc}")
    return out


def refresh_models_payload(client=None, cache_path=None):
    """Fetch the model list into the cache. ``{"count": n, "error": str | None}``."""
    if client is None:
        client = _env_client("OPENROUTER_API_KEY")
    if client is None:
        return {"count": 0, "error": "OPENROUTER_API_KEY is not set"}
    kwargs = {"cache_path": cache_path} if cache_path else {}
    models, error = model_list.get_models(client, refresh=True, **kwargs)
    return {"count": len(models), "error": error}
