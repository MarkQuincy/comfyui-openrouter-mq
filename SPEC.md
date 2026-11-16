# SPEC: ComfyUI OpenRouter nodes

_Design document for v1. The project was implemented by an AI coding assistant
(Claude, via Claude Code) following this spec, milestone by milestone, with human testing._

## Goal
A ComfyUI custom node pack that generates images through OpenRouter with the user's
own API key (not Comfy credits), and saves every result with a full, machine-readable
recipe so that a later tool (an image catalog, an agent) can explain how any image was made.

Typical use: one or more people each run their own ComfyUI on Windows (they may
share one OpenRouter account) and make many portraits of different people in one style.
Per person, the user copies a set of nodes, changes the prompt and reference photo,
optionally switches model, and presses Run.

ComfyUI logic is kept: one run = one image per Generate node. Re-generate = run again
(seed control "randomize"). 4 variants = 4 Generate nodes (branches).

Code, comments and docs: English. Node labels: English (ComfyUI convention).

## Install model (how a custom node works)
- The repo folder is linked into `ComfyUI\custom_nodes\comfyui-openrouter`
  (PowerShell: `New-Item -ItemType Junction`), ComfyUI is restarted, nodes appear
  under the category `OpenRouter`.
- `__init__.py` exports `NODE_CLASS_MAPPINGS`, `NODE_DISPLAY_NAME_MAPPINGS`,
  `WEB_DIRECTORY = "./web"` (front-end JS for the balance/cost display).
- Code runs inside ComfyUI's own Python. **No extra pip installs**: use the standard
  library (`urllib`, `json`, `hashlib`) plus what ComfyUI already ships
  (`torch`, `numpy`, `Pillow`, `aiohttp` for the server route).
- Pure logic (client, sorting, naming, metadata) lives in modules that do not import
  ComfyUI, so it is testable with plain `pytest` outside ComfyUI.

## Config
Environment variables (per PC):
- `OPENROUTER_API_KEY` (required). Never written to workflows, PNGs, logs or the repo.
- `OPENROUTER_USER` (author name stored in metadata; default: Windows user name).
- `OPENROUTER_MANAGEMENT_KEY` (optional; only for account credit balance, see M4).
- `OPENROUTER_OUTPUT_DIR` (where Save writes; default: ComfyUI output dir + `\openrouter`).
  This folder is synced between users by an external tool (Syncthing/Dropbox) — not our code.

Files next to the node (git-ignored, user-editable, created on first run):
- `user/favorites.json` — list of favorite model ids.
- `user/models_cache.json` — last fetched model list (so ComfyUI starts offline).
- `user/settings.json` — filename pattern and similar options.

## OpenRouter API (read the official docs before coding)
https://openrouter.ai/docs/features/multimodal/image-generation
- Base `https://openrouter.ai/api/v1`, header `Authorization: Bearer <key>`.
- `GET /images/models`: `data[]` with `id`, `name`, `created`, `architecture.input_modalities`,
  `architecture.output_modalities`, `supported_parameters`, `endpoints`.
- `POST /images`: `model`, `prompt`, optional `input_references`, `aspect_ratio`,
  `resolution`, `quality`, `output_format`, `seed`, `n`. Response `data[].b64_json`, `usage.cost`.
- `GET /key`: key info incl. `limit_remaining` (works with the normal key).
- `GET /credits`: `total_credits`, `total_usage` — **requires a management key**.
Rules (ported from an earlier, already tested client): send only parameters the model lists in `supported_parameters`;
402 → clear "no credits / key limit" error, not retried; 429, 5xx and network errors
→ max 2 retries with exponential backoff; other 4xx not retried.
Reference limit per model: from model info if present, else 2.

## Nodes

### OpenRouter Prompt
- Widget: `text` (multiline). Output: `STRING`.
- Any other STRING node (e.g. prompt-combine nodes) may be used instead.

### OpenRouter Context
- Widgets: `project`, `person` (text). Output: `OR_CONTEXT`.
- One per person, wired to all Generate nodes of that person (face → full body → tweaks),
  so these values are typed once.

### OpenRouter Generate
- Inputs: `prompt` (STRING, connected), `context` (OR_CONTEXT, optional),
  `ref_1` … `ref_4` (IMAGE, optional; a batch counts as several refs).
- Widgets: `model` (dropdown, sorted, see below), `aspect_ratio`, `resolution`,
  `quality`, `seed` (with ComfyUI "control after generate"), `name` (short label
  such as `face`, `fullbody`, `fix-hands`), optional `folder` (empty = main output
  folder; relative = subfolder of it; absolute path = used as is). Added 2026-11-16.
- Parameters the chosen model does not support are not sent (shown as a warning in the
  console, not an error).
- Outputs: `IMAGE` (usable by any other node, including another Generate's ref input),
  `STRING` info (model, cost, seed, file name).
- Each run saves the image (see "Saving and metadata") — no separate Save node needed.
- Shows on the node: cost of the last run and the remaining key balance (M4).
- Errors are raised as readable exceptions (ComfyUI shows them on the node).

### Model dropdown order
1. Family = author part of the id (`google/…` → `google`), families A→Z.
2. Within a family: favorites first.
3. Then by `created`, newest first.
Display label example: `★ google / gemini-3-pro-image`. Only models whose
`output_modalities` include `image`. A "refresh models" action updates the cache.

## Saving and metadata
File name from a pattern (configurable in `user/settings.json`), default:
`{date}_{project}_{person}_{name}_{model}_{counter}.png`
e.g. `2026-11-16_ProjectX_IvanPetrov_fullbody_gemini-3-pro-image_003.png`.
Empty parts are dropped, unsafe characters replaced, never overwrites (counter).

PNG text chunks:
- `prompt`, `workflow` — the standard ComfyUI chunks (same as the core Save Image node),
  so ComfyUI can re-open the workflow by dropping the PNG.
- `openrouter` — JSON, schema below. This is the **contract** for tools that read the metadata;
  change it only with a version bump.

```json
{
  "schema": "openrouter-meta/1",
  "created_at": "2026-11-16T14:03:22+03:00",
  "author": "alice",
  "project": "ProjectX",
  "person": "Ivan Petrov",
  "name": "fullbody",
  "model": "google/gemini-3-pro-image",
  "prompt": "…",
  "params": {"aspect_ratio": "3:4", "resolution": "2K", "seed": 1234},
  "params_sent": ["aspect_ratio", "resolution"],
  "cost_usd": 0.039,
  "pixel_hash": "sha256:…",
  "refs": [{"pixel_hash": "sha256:…", "width": 1024, "height": 1024}],
  "node_id": "12",
  "comfyui_prompt_id": "…"
}
```

Lineage: `pixel_hash` = sha256 of the decoded 8-bit RGB(A) pixels (width, height,
mode, raw bytes). Exact input: the ASCII text `"<width>x<height>:<mode>:"` (e.g.
`"1024x1536:RGB:"`) followed by the raw row-major 8-bit pixel bytes; result written as
`sha256:<hex>`. It is computed for every output and every reference. If a ref is
the output of another Generate (directly or via Load Image of the saved PNG), its hash
equals that image's `pixel_hash`, so the parent is known. If a ref passed through other
nodes that change pixels (face restore, upscale), the link is unknown — acceptable.

## Milestones (one per session)
Each ends with: `pytest` passes, progress notes updated, `git commit`.
Steps marked USER need a human with a real ComfyUI (and real money).

### M0 Skeleton + Prompt node
Repo layout, `pyproject.toml` (dev: pytest), `__init__.py`, Prompt node, README
install steps (junction into `custom_nodes`), `.gitignore`.
Check: pytest (import + node definition test). USER: node appears in ComfyUI.

### M1 OpenRouter client + model list
Port the earlier tested client to stdlib `urllib` (same rules and tests, fake transport).
Model list fetch + cache file + sort (family → favorites → created) + favorites file.
Check: tests for retries (real retry path, not only a fake client), 402, param filtering,
sort order, offline start from cache.

### M2 Generate + Context nodes
Nodes as specified; IMAGE tensor ↔ PNG/data-URL conversion; refs capped per model.
Check: tests with fake transport (tensor shapes, refs, unsupported params dropped).
USER: one real generation in ComfyUI, chain face → full body works.

### M3 Saving and metadata
Filename pattern, no overwrite, PNG chunks (`prompt`, `workflow`, `openrouter`),
pixel hashes and refs.
Check: tests read back the chunks; hash of a saved PNG reloaded with Pillow equals the
stored `pixel_hash`. USER: drop the PNG into ComfyUI → workflow opens.

### M4 Cost and balance on the node
Server route (PromptServer) returning key `limit_remaining` (and account credits if
`OPENROUTER_MANAGEMENT_KEY` is set); JS in `web/` shows last cost + balance on the
Generate node and a refresh button.
Check: tests for the route logic. USER: values visible and refresh works.

### M5 Example workflows + docs
`examples/`: single person, face → full body → tweak chain, 4 variants, model comparison
(one prompt → several Generate nodes). README with usage.

### M6 Audio, video and JSON recipes (v1.1)
Docs: https://openrouter.ai/docs/features/multimodal/tts and
https://openrouter.ai/docs/features/multimodal/video-generation
- **JSON recipe next to every saved file** (images too): `name_001.png` →
  `name_001.json`, never overwritten. Content = the metadata dict with
  `"schema": "openrouter-meta/2"` plus `kind` (`image`/`audio`/`video`), `file`
  (file name) and `file_hash` (`sha256:` of the saved file bytes). For audio/video
  `pixel_hash` is null. The PNG `openrouter` chunk stays `openrouter-meta/1`, unchanged.
- **OpenRouter Speak** node: `text` (STRING, connected), `context`, widgets `model`
  (speech models from `GET /models?output_modalities=speech`), `voice` (text, empty
  = model default; not sent when empty), `format` (`mp3`/`pcm`), `speed`, `instructions`, `name`, `folder`.
  `POST /audio/speech` returns raw audio. Saves `.mp3`, or `.wav` for pcm (assumed
  24 kHz 16-bit mono). Outputs ComfyUI `AUDIO` + info. Cost is not in the response → null.
- **OpenRouter Video** node: `prompt` (STRING, connected), `context`, `first_frame`,
  `last_frame` (IMAGE, optional), widgets `model` (from `GET /videos/models`),
  `aspect_ratio`, `resolution`, `duration` (0 = model default), `generate_audio`
  (auto/on/off), `seed`, `name`, `folder`. `POST /videos` → poll `GET /videos/{id}`
  every 10 s (stops on ComfyUI cancel, gives up after 30 min) → download
  `GET /videos/{id}/content`. Values the model does not list in `supported_*` are not
  sent (warning). Saves `.mp4`; outputs the file path (STRING) + info.
  `refs` in the recipe = pixel hashes of the frames sent, so a video links back to
  the portrait it was made from.
- Speak language filter (owner request): `language` widget, first on the node and saved
  (backend ignores it); JS narrows the model dropdown via
  `GET /openrouter/speech_models?language=` (cache only). A model listed in
  `user/languages.json` gets exactly those languages (overrides the description);
  otherwise description names the language, or "multilingual" / "N languages" matches all
  languages with the label suffix `· multilingual` (stripped by `id_from_label`).
  Breaking: Speak nodes saved before this change load with shifted widget values.
- Speak error for providers that require a voice when none is set: points to the model's
  page on openrouter.ai.
- Speak voice dropdown (owner request): JS "voice list" combo on the Speak node with the
  selected model's `supported_voices` (route `GET /openrouter/voices?model=`, cache
  only); picking fills the `voice` text widget (the saved value). ♂/♀ from
  `user/voices.json`, else a provider `gender` field, else Kokoro-style `af_`/`am_`
  names; otherwise no mark.
- Model caches per kind (`user/video_models_cache.json`, `user/speech_models_cache.json`),
  same favorites file, same sort. "refresh models" refreshes all kinds.
- Cost/balance display also on Speak and Video nodes.
- Video preview on the node: the saved mp4 is copied to ComfyUI's temp folder and
  returned as `ui.images` + `animated` (like ComfyUI's own video nodes).
- **OpenRouter Cost Report** node (owner request): sums `cost_usd` from `.json` recipes
  (and the `openrouter` PNG chunk of older images without one) under a folder, grouped by
  project/person/model/kind/date/author, optional `since` date. Read-only.
- Video model info on the node (owner request): route
  `GET /openrouter/video_model?model=&resolution=&duration=&audio=` (cache only) returns
  display lines + allowed durations from `video_cost.info_lines`. Real data (Seedance 2.0
  Fast): `pricing_skus` = `video_tokens`, `video_tokens_without_audio`,
  `video_tokens_with_video_input` (USD per token). Seedance rule: tokens = w×h×24×s/1024
  (480p = 854×480 → $0.04035/s, matches openrouter.ai). Token SKUs for other models →
  no estimate; non-token SKUs → shown as "per s (assumed unit)". Duration widget max =
  longest allowed length; a non-allowed value snaps to the nearest allowed one.
- Not in scope: ComfyUI VIDEO output type, Transcribe node, audio/video references,
  editing/extending a video (`previous_job_id`).
Check: tests with fake transport (speech bytes, video submit → poll → download,
failed job, unsupported values dropped, JSON recipes for all kinds).
USER: one real speech and one real short video in ComfyUI.

### Later
- "AI gate": a local agent (Ollama/Hermes via MCP) writes text into a chosen Prompt node.
- Structured prompt (constant style block + changing person block).
</content>
</invoke>
