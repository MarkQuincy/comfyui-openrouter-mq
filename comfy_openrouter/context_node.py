"""OpenRouter Context node: project + person, typed once per person."""

from .prompt_node import CATEGORY


class OpenRouterContext:
    CATEGORY = CATEGORY
    RETURN_TYPES = ("OR_CONTEXT",)
    RETURN_NAMES = ("context",)
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project": ("STRING", {"default": ""}),
                "person": ("STRING", {"default": ""}),
            }
        }

    def run(self, project, person):
        return ({"project": project.strip(), "person": person.strip()},)
