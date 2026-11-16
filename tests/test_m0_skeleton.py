"""M0: the pack imports like ComfyUI loads it, and the Prompt node is well defined."""

import importlib.util
import sys
from pathlib import Path

from comfy_openrouter.prompt_node import OpenRouterPrompt

ROOT = Path(__file__).resolve().parent.parent


def load_pack():
    """Import the repo root as a package, the way ComfyUI imports custom_nodes folders."""
    name = "comfyui_openrouter_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_pack_exports():
    pack = load_pack()
    assert pack.NODE_CLASS_MAPPINGS["OpenRouterPrompt"].__name__ == "OpenRouterPrompt"
    assert set(pack.NODE_DISPLAY_NAME_MAPPINGS) == set(pack.NODE_CLASS_MAPPINGS)
    assert pack.NODE_DISPLAY_NAME_MAPPINGS["OpenRouterPrompt"] == "OpenRouter Prompt"
    assert pack.WEB_DIRECTORY == "./web"
    assert (ROOT / "web").is_dir()


def test_prompt_node_definition():
    inputs = OpenRouterPrompt.INPUT_TYPES()
    kind, options = inputs["required"]["text"]
    assert kind == "STRING"
    assert options["multiline"] is True
    assert OpenRouterPrompt.RETURN_TYPES == ("STRING",)
    assert OpenRouterPrompt.CATEGORY == "OpenRouter"
    assert callable(getattr(OpenRouterPrompt(), OpenRouterPrompt.FUNCTION))


def test_prompt_node_returns_text():
    assert OpenRouterPrompt().run("a portrait, studio light") == ("a portrait, studio light",)
