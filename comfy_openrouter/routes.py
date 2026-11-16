"""HTTP routes on ComfyUI's server, used by ``web/openrouter.js``.

GET  /openrouter/balance         -> balance.balance_payload()
GET  /openrouter/voices?model=…   -> voices.voices_payload()
GET  /openrouter/speech_models?language=… -> languages.speech_models_payload()
GET  /openrouter/video_model?model=&resolution=&duration=&audio= -> video_cost.info_lines()
POST /openrouter/refresh_models  -> balance.refresh_models_payload()

The OpenRouter calls block, so they run in a worker thread.
"""

import asyncio
import logging

from . import balance, languages, video_cost, voices

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

    @routes.get("/openrouter/video_model")
    async def get_video_model(request):
        q = request.query
        try:
            duration = int(q.get("duration", "0") or 0)
        except ValueError:
            duration = 0
        return web.json_response(video_cost.info_lines(
            q.get("model", ""), q.get("resolution", "auto"), duration, q.get("audio", "auto")))

    @routes.get("/openrouter/speech_models")
    async def get_speech_models(request):
        language = request.query.get("language", languages.ALL)
        return web.json_response(languages.speech_models_payload(language))

    return True
