"""OpenRouter Cost Report node: totals of saved files' costs, shown on the node."""

from . import report
from .generate_node import output_dir
from .prompt_node import CATEGORY


class OpenRouterCostReport:
    CATEGORY = CATEGORY
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("report",)
    FUNCTION = "run"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "group_by": (report.GROUPS, {"default": "project"}),
                "since": ("STRING", {"default": "", "tooltip":
                          "Only files from this date on, e.g. 2026-11-01. Empty = all."}),
            },
            "optional": {
                "folder": ("STRING", {"default": "", "tooltip":
                           "Same as on Generate: empty = main output folder, a name = "
                           "subfolder, a full path = that folder."}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")  # files change outside ComfyUI: always re-read

    def run(self, group_by, since, folder=""):
        rows = report.summarize(report.collect(output_dir(folder)), group_by, since.strip())
        text = report.format_report(rows, group_by)
        return {"ui": {"openrouter_report": [text]}, "result": (text,)}
