"""ComfyUI entry point for the OpenRouter node pack."""

if __package__:  # loaded by ComfyUI as a package
    from .comfy_openrouter.context_node import OpenRouterContext
    from .comfy_openrouter.generate_node import OpenRouterGenerate
    from .comfy_openrouter.prompt_node import OpenRouterPrompt
    from .comfy_openrouter.routes import register as register_routes
else:  # pytest imports the repo root __init__.py as a plain module
    from comfy_openrouter.context_node import OpenRouterContext
    from comfy_openrouter.generate_node import OpenRouterGenerate
    from comfy_openrouter.prompt_node import OpenRouterPrompt
    from comfy_openrouter.routes import register as register_routes

register_routes()  # balance + refresh routes; does nothing outside ComfyUI

NODE_CLASS_MAPPINGS = {
    "OpenRouterPrompt": OpenRouterPrompt,
    "OpenRouterContext": OpenRouterContext,
    "OpenRouterGenerate": OpenRouterGenerate,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "OpenRouterPrompt": "OpenRouter Prompt",
    "OpenRouterContext": "OpenRouter Context",
    "OpenRouterGenerate": "OpenRouter Generate",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
