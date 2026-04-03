"""AI translator — NL → pipeline steps. API key never leaves the server."""
import json
import logging
import httpx
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AI Data Pipeline Translator.
Convert natural language into structured JSON pipeline steps.

RULES:
- Output ONLY valid JSON. No prose. No markdown. No code blocks.
- Only use the allowed actions listed below.
- Do NOT assume column names unless the user provides them explicitly.
- If the request is unclear → return {"steps":[]}.

Allowed actions:
drop_nulls, fill_nulls, remove_outliers, normalize, standardize,
encode_categorical, filter_rows, select_columns, drop_columns,
sort_values, groupby_aggregate, remove_duplicates, convert_types

Output schema — return EXACTLY this shape, nothing else:
{"steps":[{"action":"action_name","params":{"columns":[],"method":"","threshold":null,"order":""}}]}

Allowed param keys ONLY: columns (string[]), method (string), threshold (number|null), order ("asc"|"desc"|"")
No other keys. No explanation. No markdown."""


async def translate_to_steps(prompt: str, dataset_columns: list[str] | None = None) -> dict:
    """Returns raw parsed JSON from the AI. Never raises — returns {steps:[]} on any failure."""
    if not settings.ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not configured")
        return {"steps": [], "error": "AI service not configured"}

    user_msg = prompt
    if dataset_columns:
        user_msg = f"Available dataset columns: {dataset_columns}\n\nUser request: {prompt}"

    try:
        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1000,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = "".join(b.get("text", "") for b in data.get("content", [])).strip()
            text = text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("AI returned non-JSON: %s", e)
        return {"steps": []}
    except Exception as exc:
        logger.error("AI translation failed: %s", exc)
        return {"steps": [], "error": str(exc)[:200]}


EXPLAIN_SYSTEM_PROMPT = """You are an AI Data Pipeline Explainer.
Given a JSON list of data processing steps, explain what the pipeline does in natural language.
RULES:
- Explain clearly and concisely.
- Do NOT output JSON. Output readable prose.
- Limit output to 3-5 sentences.
"""

async def explain_steps(steps: list[dict]) -> tuple[str, str | None]:
    """Returns (explanation, error)"""
    if not settings.ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not configured")
        return "AI service not configured.", "API Key missing"

    user_msg = f"Explain this pipeline:\n{json.dumps(steps, indent=2)}"

    try:
        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 500,
                    "system": EXPLAIN_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = "".join(b.get("text", "") for b in data.get("content", [])).strip()
            return text, None
    except Exception as exc:
        logger.error("AI Explanation failed: %s", exc)
        return "Failed to explain pipeline.", str(exc)[:200]
