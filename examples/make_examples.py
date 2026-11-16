"""Build the example workflows in this folder (dev tool; not needed inside ComfyUI).

Run from the repo root:  uv run python examples/make_examples.py
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = "google / gemini-3-pro-image"  # change in the dropdown after loading
SPEECH_MODEL = "openai / gpt-4o-mini-tts-2025-12-15"
VIDEO_MODEL = "google / veo-3.1"

# Widget order must match INPUT_TYPES (seed is followed by its "control after generate").
GENERATE_INPUTS = [("prompt", "STRING"), ("context", "OR_CONTEXT"), ("ref_1", "IMAGE"),
                   ("ref_2", "IMAGE"), ("ref_3", "IMAGE"), ("ref_4", "IMAGE")]
GENERATE_OUTPUTS = [("image", "IMAGE"), ("info", "STRING")]


class Workflow:
    def __init__(self):
        self.nodes, self.links = [], []

    def _node(self, type_, pos, size, widgets, inputs=(), outputs=(), title=None):
        node = {
            "id": len(self.nodes) + 1, "type": type_, "pos": list(pos), "size": list(size),
            "flags": {}, "order": len(self.nodes), "mode": 0,
            "inputs": [{"name": n, "type": t, "link": None} for n, t in inputs],
            "outputs": [{"name": n, "type": t, "links": []} for n, t in outputs],
            "properties": {"Node name for S&R": type_},
            "widgets_values": widgets,
        }
        if title:
            node["title"] = title
        self.nodes.append(node)
        return node

    def note(self, pos, text, size=(420, 160)):
        return self._node("Note", pos, size, [text])

    def prompt(self, pos, text):
        return self._node("OpenRouterPrompt", pos, (400, 180), [text],
                          outputs=[("prompt", "STRING")])

    def context(self, pos, project, person):
        return self._node("OpenRouterContext", pos, (320, 90), [project, person],
                          outputs=[("context", "OR_CONTEXT")])

    def load_image(self, pos, filename="example.png"):
        return self._node("LoadImage", pos, (320, 320), [filename, "image"],
                          outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")])

    def generate(self, pos, name, model=MODEL, aspect="3:4", seed=0, title=None):
        widgets = [model, aspect, "auto", "auto", seed, "randomize", name, ""]
        return self._node("OpenRouterGenerate", pos, (360, 430), widgets,
                          inputs=GENERATE_INPUTS, outputs=GENERATE_OUTPUTS, title=title)

    def speak(self, pos, name, model=SPEECH_MODEL):
        widgets = [model, "alloy", "mp3", 1.0, "", name, ""]
        return self._node("OpenRouterSpeak", pos, (360, 330), widgets,
                          inputs=[("text", "STRING"), ("context", "OR_CONTEXT")],
                          outputs=[("audio", "AUDIO"), ("info", "STRING")])

    def video(self, pos, name, model=VIDEO_MODEL):
        widgets = [model, "9:16", "720p", 0, "auto", 0, "randomize", name, ""]
        return self._node("OpenRouterVideo", pos, (360, 400), widgets,
                          inputs=[("prompt", "STRING"), ("context", "OR_CONTEXT"),
                                  ("first_frame", "IMAGE"), ("last_frame", "IMAGE")],
                          outputs=[("file", "STRING"), ("info", "STRING")])

    def preview_audio(self, pos):
        return self._node("PreviewAudio", pos, (320, 120), [],
                          inputs=[("audio", "AUDIO")])

    def link(self, src, src_slot, dst, dst_name):
        dst_slot = next(i for i, x in enumerate(dst["inputs"]) if x["name"] == dst_name)
        type_ = src["outputs"][src_slot]["type"]
        link_id = len(self.links) + 1
        self.links.append([link_id, src["id"], src_slot, dst["id"], dst_slot, type_])
        src["outputs"][src_slot]["links"].append(link_id)
        dst["inputs"][dst_slot]["link"] = link_id

    def to_json(self):
        return {
            "last_node_id": len(self.nodes), "last_link_id": len(self.links),
            "nodes": self.nodes, "links": self.links, "groups": [], "config": {},
            "extra": {}, "version": 0.4,
        }


def single_person():
    w = Workflow()
    w.note((40, 40), "One person, one image per run.\n\n1. Type project and person once in "
           "Context.\n2. Load the reference photo.\n3. Pick a model and press Run.\n"
           "Seed is 'randomize': Run again for another variant.")
    ctx = w.context((40, 240), "ProjectX", "Ivan Petrov")
    ref = w.load_image((40, 380))
    p = w.prompt((500, 40), "Studio portrait of the person in the reference photo, "
                 "soft light, neutral grey background.")
    gen = w.generate((960, 40), "face")
    w.link(p, 0, gen, "prompt")
    w.link(ctx, 0, gen, "context")
    w.link(ref, 0, gen, "ref_1")
    return w


def face_fullbody_tweak():
    w = Workflow()
    w.note((40, 40), "Chain: face -> full body -> fix.\n\nEach step uses the previous "
           "image as ref_1. All steps share one Context, so every file gets the same "
           "project and person, and the metadata links each child to its parent.")
    ctx = w.context((40, 240), "ProjectX", "Ivan Petrov")
    ref = w.load_image((40, 380))
    steps = [
        ("face", "Head-and-shoulders portrait of the person in the reference, studio light."),
        ("fullbody", "Full body shot of the same person, same outfit and light, "
                     "standing, neutral background."),
        ("fix-hands", "Same image, keep everything, fix the hands so they look natural."),
    ]
    previous = ref
    for i, (name, text) in enumerate(steps):
        x = 420 + i * 420
        p = w.prompt((x, 40), text)
        gen = w.generate((x, 260), name)
        w.link(p, 0, gen, "prompt")
        w.link(ctx, 0, gen, "context")
        w.link(previous, 0, gen, "ref_1")
        previous = gen
    return w


def four_variants():
    w = Workflow()
    w.note((40, 40), "4 variants = 4 Generate nodes (branches) with the same prompt.\n"
           "Each has its own random seed. One Run makes 4 images.")
    ctx = w.context((40, 240), "ProjectX", "Ivan Petrov")
    ref = w.load_image((40, 380))
    p = w.prompt((40, 740), "Studio portrait of the person in the reference photo.")
    for i in range(4):
        gen = w.generate((480 + i * 400, 40), f"variant{i + 1}", seed=i)
        w.link(p, 0, gen, "prompt")
        w.link(ctx, 0, gen, "context")
        w.link(ref, 0, gen, "ref_1")
    return w


def model_comparison():
    w = Workflow()
    w.note((40, 40), "Model comparison: one prompt -> several Generate nodes.\n"
           "Pick a DIFFERENT model in each Generate after loading. The model is part of "
           "the file name, so results are easy to compare.")
    ctx = w.context((40, 240), "ModelTest", "Ivan Petrov")
    ref = w.load_image((40, 380))
    p = w.prompt((40, 740), "Studio portrait of the person in the reference photo.")
    for i in range(3):
        gen = w.generate((480 + i * 400, 40), "compare", title=f"Model {i + 1} (pick one)")
        w.link(p, 0, gen, "prompt")
        w.link(ctx, 0, gen, "context")
        w.link(ref, 0, gen, "ref_1")
    return w


def speak_text():
    w = Workflow()
    w.note((40, 40), "Text to speech. The audio is saved (mp3, or wav for 'pcm') with a "
           "JSON recipe next to it, and goes to Preview Audio.\nVoices depend on the "
           "model (e.g. alloy, nova for OpenAI).")
    ctx = w.context((40, 240), "ProjectX", "Ivan Petrov")
    p = w.prompt((420, 40), "Hello! This voice was made with OpenRouter in ComfyUI.")
    sp = w.speak((860, 40), "intro")
    out = w.preview_audio((1260, 40))
    w.link(p, 0, sp, "text")
    w.link(ctx, 0, sp, "context")
    w.link(sp, 0, out, "audio")
    return w


def portrait_to_video():
    w = Workflow()
    w.note((40, 40), "Portrait -> video. Generate makes the portrait, Video uses it as the "
           "first frame. Video jobs take minutes and cost more than images. The MP4 and "
           "its JSON recipe link back to the portrait by pixel hash.")
    ctx = w.context((40, 240), "ProjectX", "Ivan Petrov")
    ref = w.load_image((40, 380))
    p = w.prompt((420, 40), "Studio portrait of the person in the reference photo, "
                 "full body, plain background.")
    gen = w.generate((420, 260), "fullbody", aspect="9:16")
    pv = w.prompt((860, 40), "The person smiles and slowly turns towards the camera.")
    vid = w.video((860, 260), "turn")
    w.link(p, 0, gen, "prompt")
    w.link(ctx, 0, gen, "context")
    w.link(ref, 0, gen, "ref_1")
    w.link(pv, 0, vid, "prompt")
    w.link(ctx, 0, vid, "context")
    w.link(gen, 0, vid, "first_frame")
    return w


EXAMPLES = {
    "01_single_person.json": single_person,
    "02_face_fullbody_tweak.json": face_fullbody_tweak,
    "03_four_variants.json": four_variants,
    "04_model_comparison.json": model_comparison,
    "05_speak.json": speak_text,
    "06_portrait_to_video.json": portrait_to_video,
}


def main():
    for filename, build in EXAMPLES.items():
        text = json.dumps(build().to_json(), indent=2, ensure_ascii=False) + "\n"
        (HERE / filename).write_text(text, encoding="utf-8")
        print("wrote", filename)


if __name__ == "__main__":
    main()
