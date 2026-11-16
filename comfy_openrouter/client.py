"""OpenRouter Image API client (stdlib only).

Ported from an earlier, tested client: same retry and error rules, but the HTTP
layer is ``urllib`` and is injectable (``transport``) so tests never touch the network.
The API key is passed in by the caller and is never logged or shown in ``repr``.

Docs: https://openrouter.ai/docs/features/multimodal/image-generation
"""

import base64
import json
import time
import urllib.error
import urllib.request

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MAX_REFS = 2
RETRYABLE = {429, 500, 502, 503, 504}


class OpenRouterError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoCreditsError(OpenRouterError):
    """HTTP 402: no credits / key limit reached."""


class RateLimitError(OpenRouterError):
    """HTTP 429 after retries are exhausted."""


class ServerError(OpenRouterError):
    """HTTP 5xx after retries are exhausted."""


class UnknownModelError(OpenRouterError):
    """Model is not in the OpenRouter image model list."""


class NetworkError(OpenRouterError):
    """Connection failed, timed out, or the response was not readable."""


# -- transport -----------------------------------------------------------------


def urllib_transport(method, url, headers, body, timeout):
    """Send one request. Returns ``(status, payload)``; raises ``NetworkError``."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, _parse_json(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _parse_json(exc.read())
    except (urllib.error.URLError, OSError) as exc:
        raise NetworkError(f"network error: {exc}") from exc


def _parse_json(raw):
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        return None


# -- model info helpers (entries of GET /images/models) ----------------------


def accepts_images(model):
    arch = model.get("architecture") or {}
    return "image" in (arch.get("input_modalities") or model.get("input_modalities") or [])


def outputs_images(model):
    arch = model.get("architecture") or {}
    return "image" in (arch.get("output_modalities") or model.get("output_modalities") or [])


def supported_params(model):
    params = model.get("supported_parameters") or {}
    if isinstance(params, list):  # tolerate a list form
        return {name: {} for name in params}
    return params


def max_refs(model):
    """Max reference images: ``input_references.max`` if present, else 2 (SPEC)."""
    if not accepts_images(model):
        return 0
    desc = supported_params(model).get("input_references")
    if isinstance(desc, dict) and isinstance(desc.get("max"), int) and desc["max"] > 0:
        return desc["max"]
    return DEFAULT_MAX_REFS


def filter_params(model, params):
    """Split ``params`` into ``(sent, dropped)`` by the model's supported parameters.

    A value outside the model's listed ``values`` (enum) is dropped too.
    Empty values (None, "") are neither sent nor reported as dropped.
    """
    supported = supported_params(model)
    sent, dropped = {}, []
    for key, value in (params or {}).items():
        if value in (None, ""):
            continue
        desc = supported.get(key)
        allowed = desc.get("values") if isinstance(desc, dict) else None
        if key in supported and (not isinstance(allowed, list) or value in allowed):
            sent[key] = value
        else:
            dropped.append(key)
    return sent, dropped


# -- client --------------------------------------------------------------------


class GenerationResult:
    def __init__(self, images, cost, params_sent, params_dropped):
        self.images = images  # list of raw image bytes
        self.cost = cost
        self.params_sent = params_sent  # list of parameter names actually sent
        self.params_dropped = params_dropped  # unsupported by the model, not sent


class OpenRouterClient:
    """``retries`` = extra attempts after the first (429/5xx/network only)."""

    def __init__(self, api_key, base_url=BASE_URL, timeout=180.0, retries=2,
                 backoff=1.0, transport=urllib_transport, sleep=time.sleep):
        if not api_key:
            raise ValueError("OpenRouter API key is missing (set OPENROUTER_API_KEY)")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._transport = transport
        self._sleep = sleep

    def __repr__(self):  # never show the key
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    def _request(self, method, path, payload=None):
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        url = self.base_url + path

        for attempt in range(self.retries + 1):
            last = attempt == self.retries
            try:
                status, data = self._transport(method, url, headers, body, self.timeout)
            except NetworkError:
                if last:
                    raise
            else:
                if status < 400:
                    return data
                message = _error_message(status, data)
                if status == 402:
                    raise NoCreditsError(
                        f"{message} (no credits left or key limit reached)", status=status)
                if status not in RETRYABLE:
                    raise OpenRouterError(message, status=status)
                if last:
                    cls = RateLimitError if status == 429 else ServerError
                    raise cls(message, status=status)
            self._sleep(self.backoff * (2 ** attempt))
        raise AssertionError("unreachable")

    # -- endpoints ---------------------------------------------------------------

    def list_models(self):
        """All image models (``GET /images/models``), uncached."""
        return (self._request("GET", "/images/models") or {}).get("data") or []

    def key_status(self):
        """Key info (``GET /key``); includes ``limit_remaining``."""
        data = self._request("GET", "/key") or {}
        return data.get("data", data)

    def credits(self):
        """Account credits (``GET /credits``); needs a management key."""
        data = self._request("GET", "/credits") or {}
        return data.get("data", data)

    def generate(self, model, prompt, params=None, refs=None):
        """Generate images. ``model`` is a model info dict from ``list_models``.

        ``refs`` are base64 data URLs (or HTTP(S) URLs). Only supported parameters
        are sent; refs are capped at the model's limit.
        """
        if not isinstance(model, dict) or not model.get("id"):
            raise UnknownModelError(f"unknown model: {model!r}")
        sent, dropped = filter_params(model, params)
        payload = {"model": model["id"], "prompt": prompt, **sent}
        limit = max_refs(model)
        if refs and limit:
            payload["input_references"] = [
                {"type": "image_url", "image_url": {"url": url}} for url in refs[:limit]
            ]

        data = self._request("POST", "/images", payload) or {}
        images = []
        for item in data.get("data") or []:
            try:
                images.append(base64.b64decode(item["b64_json"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise OpenRouterError(f"bad image in response: {exc}") from exc
        if not images:
            raise OpenRouterError("response contains no images")
        cost = (data.get("usage") or {}).get("cost")
        return GenerationResult(images, cost, list(sent), dropped)


def _error_message(status, data):
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict) and err.get("message"):
        return f"OpenRouter HTTP {status}: {err['message']}"
    return f"OpenRouter HTTP {status}"
