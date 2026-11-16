"""OpenRouter Prompt node: multiline text -> STRING."""

CATEGORY = "OpenRouter"


class OpenRouterPrompt:
    CATEGORY = CATEGORY
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"multiline": True, "default": ""})}}

    def run(self, text):
        return (text,)
