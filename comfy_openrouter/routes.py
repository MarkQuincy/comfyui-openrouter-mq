"""HTTP routes on ComfyUI's server, used by ``web/openrouter.js``.

GET  /openrouter/balance         -> balance.balance_payload()
GET  /openrouter/voices?model=…   -> voices.voices_payload()
GET  /openrouter/speech_models?language=… -> languages.speech_models_payload()
POST /openrouter/refresh_models  -> balance.refresh_models_payload()

The OpenRouter calls block, so they run in a worker thread.
"""

import asyncio
import logging

from . import balance, languages, voices

log = logging.getLogger("comfyui-openrouter")


def register():
    """Add the routes when running inside ComfyUI. Returns False outside ComfyUI."""
    try:
        from aiohttp import web
        from server import PromptServer  # ComfyUI module
    except ImportError:
        return False

    routes = PromptServer.instance.routes

    @routes.get("/openrouter/balance")
    async def get_balance(request):
        return web.json_response(await asyncio.to_thread(balance.balance_payload))

    @routes.post("/openrouter/refresh_models")
    async def refresh_models(request):
        result = await asyncio.to_thread(balance.refresh_models_payload)
        if result["error"]:
            log.warning("[OpenRouter] %s", result["error"])
        return web.json_response(result)

    @routes.get("/openrouter/voices")
    async def get_voices(request):
        model = request.query.get("model", "")
        return web.json_response(voices.voices_payload(model))

    @routes.get("/openrouter/speech_models")
    async def get_speech_models(request):
        language = request.query.get("language", languages.ALL)
        return web.json_response(languages.speech_models_payload(language))

    return True
