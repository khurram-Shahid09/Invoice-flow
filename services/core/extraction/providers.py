"""AI providers (docs/06 "Provider interface"): Gemini, and a fake for tests and offline demos.

Gemini runs on free-tier keys: several keys and models are tried in order, and a key/model
that hits its quota is skipped for an hour, so a demo never waits on an exhausted key.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings

from .schema import PROMPT, PROMPT_VERSION, Extraction

log = logging.getLogger(__name__)
COOLDOWN_S = 3600
_exhausted: dict[tuple[int, str], float] = {}  # (key index, model) -> retry after


class ExtractionError(Exception):
    """The document couldn't be read. ``message`` is shown to the clerk."""


@dataclass
class Result:
    extraction: Extraction
    provider: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    ms: int = 0
    trusted: bool = False  # answer key (fake provider): no need to ground
    meta: dict[str, Any] = field(default_factory=dict)


def extract(images: list[bytes], text_pages: list[str], filename: str) -> Result:
    provider = settings.LLM_PROVIDER
    if provider == "gemini":
        return _gemini(images, text_pages)
    if provider == "fake":
        return _fake(filename)
    raise ExtractionError(f"Unknown LLM_PROVIDER {provider!r}")


def _gemini(images: list[bytes], text_pages: list[str]) -> Result:
    from google import genai
    from google.genai import errors, types

    if not settings.GEMINI_API_KEYS:
        raise ExtractionError("No Gemini API key is configured.")
    text = "\n".join(f"<page {i}>\n{t}\n</page>" for i, t in enumerate(text_pages, 1) if t)
    contents: list[Any] = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images]
    contents.append(
        f"Text layer of the PDF (empty for scans and photos):\n{text}" if text else "No text layer."
    )
    config = types.GenerateContentConfig(
        system_instruction=PROMPT,
        response_mime_type="application/json",
        response_schema=Extraction,
        temperature=0,
    )
    last_error = "every key and model is over its free-tier limit; try again later"
    for model in settings.GEMINI_MODELS:
        for index, key in enumerate(settings.GEMINI_API_KEYS):
            if _exhausted.get((index, model), 0) > time.time():
                continue
            started = time.monotonic()
            try:
                response = genai.Client(api_key=key).models.generate_content(
                    model=model, contents=contents, config=config
                )
            except errors.APIError as exc:
                if exc.code in (429, 403):  # quota or key problem: skip this key for a while
                    _exhausted[(index, model)] = time.time() + COOLDOWN_S
                    log.warning("Gemini key %d on %s unavailable (%s)", index + 1, model, exc.code)
                    continue
                if exc.code in (500, 503, 504):  # overloaded model: try the next one
                    last_error = f"{model} is overloaded"
                    break
                raise ExtractionError(f"Gemini error {exc.code}") from exc
            parsed = response.parsed
            if not isinstance(parsed, Extraction):
                try:
                    parsed = Extraction.model_validate_json(response.text or "")
                except ValueError as exc:
                    raise ExtractionError("The AI's answer didn't match the schema.") from exc
            usage = response.usage_metadata
            return Result(
                parsed,
                "gemini",
                model,
                input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                output_tokens=(usage.candidates_token_count or 0) if usage else 0,
                ms=int((time.monotonic() - started) * 1000),
                meta={"key": index + 1, "prompt": PROMPT_VERSION},
            )
    raise ExtractionError(f"Gemini unavailable: {last_error}.")


def _fake(filename: str) -> Result:
    """Answer keys from the eval generator (evals/data/generated), matched by file name."""
    root = Path(settings.REPO_ROOT) / "evals" / "data" / "generated"
    manifest = root / "manifest.json"
    case = None
    if manifest.is_file():
        cases = json.loads(manifest.read_text(encoding="utf-8"))["cases"]
        case = next((c for c in cases if c["file"] == filename), None)
    if case is None:
        raise ExtractionError("Offline mode only knows the generated eval invoices.")
    truth = json.loads((root / "truth" / f"{case['id']}.json").read_text(encoding="utf-8"))

    def v(value: Any) -> dict:
        return {"value": None if value is None else str(value), "page": 1, "quote": None}

    lines = [{k: v(line.get(k)) for k in line if k != "discount_pct"} for line in truth["lines"]]
    data: dict[str, Any] = {
        name: v(truth.get(name))
        for name in Extraction.model_fields
        if name not in ("document_type", "lines", "notes_for_reviewer")
    }
    data.update(document_type=truth["document_type"], lines=lines)
    return Result(Extraction.model_validate(data), "fake", "answer-key", trusted=True)
