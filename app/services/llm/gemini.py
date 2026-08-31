"""The Gemini client: structured, retried, measured.

Everything this service sends has already been through the redactor. It is the
last hop before the network, and it is written on the assumption that the model
is a remote, fallible, occasionally-wrong dependency rather than an oracle.

Three things it handles that a bare SDK call does not:

**Structured output, validated.** The response is parsed into ``AnalisisGMM``
before it is returned. A model that emits prose, truncated JSON, or a field of
the wrong type produces an error here rather than an exception three layers up
in a route handler.

**Safety filters.** Gemini's default filters are tuned for consumer chat, and a
policy that enumerates covered conditions — oncology, HIV, psychiatric care,
maternity complications — reads to those filters like medical content worth
blocking. A blocked response on a legitimate GMM policy is a false positive that
would make the tool unusable, so the thresholds are widened deliberately and the
reason is recorded here rather than buried in a config file.

**Usage accounting.** Token counts and latency come back with every call, so the
dashboard can show what the agent costs and the eval harness can compare a
cheaper model honestly.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import (
    Any,
    Optional,
    Type,
)

from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import logger


class ModelCallError(RuntimeError):
    """Raised when no configured model could produce a valid response."""


class ModelBlockedError(ModelCallError):
    """Raised when the provider's safety filters refused the request.

    Distinguished from a generic failure because it is actionable in a
    completely different way: retrying will not help, and the operator needs to
    know the document was refused rather than that the service is broken.
    """


@dataclass
class ModelResult:
    """One successful model call.

    Attributes:
        parsed: The validated response object.
        model_name: Which model actually answered — not necessarily the primary,
            since a fallback may have taken over.
        input_tokens: Prompt tokens billed.
        output_tokens: Completion tokens billed.
        latency_ms: Wall-clock time for the call.
    """

    parsed: Any
    model_name: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


# Gemini's HarmBlockThreshold values, referenced by name so this file does not
# import the provider SDK's enums just to build a dict.
_PERMISSIVE_SAFETY = {
    "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
}

# Below this, there is no point starting another call: the connect and TLS
# handshake alone eat most of it, and the attempt would be cancelled mid-flight.
_MIN_ATTEMPT_SECONDS = 5.0


class GeminiService:
    """Calls Gemini with retries, a model fallback, and schema validation."""

    def __init__(self) -> None:
        """Initialise the client lazily.

        The model objects are built on first use rather than at import, so a
        missing API key surfaces as a clear error on the first analysis instead
        of preventing the whole service from starting — the login and dashboard
        paths do not need Gemini.
        """
        self._models: dict[str, Any] = {}

    def _get_model(self, model_name: str) -> Any:
        """Build or return a cached chat model.

        Args:
            model_name: The Gemini model id.

        Returns:
            Any: A configured ``ChatGoogleGenerativeAI``.

        Raises:
            ModelCallError: If no API key is configured.
        """
        if model_name in self._models:
            return self._models[model_name]

        if not settings.GEMINI_API_KEY:
            raise ModelCallError("GEMINI_API_KEY is not configured")

        from langchain_google_genai import ChatGoogleGenerativeAI

        model = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=settings.GEMINI_TEMPERATURE,
            max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
            timeout=settings.GEMINI_TIMEOUT_SECONDS,
            # Retries are handled here, with logging and a fallback chain, so
            # the SDK's own silent retry is turned off.
            max_retries=0,
            safety_settings=_PERMISSIVE_SAFETY,
        )

        self._models[model_name] = model
        return model

    async def structured_call(
        self,
        prompt: str,
        schema: Type[BaseModel],
        *,
        purpose: str,
    ) -> ModelResult:
        """Call Gemini and parse the answer into a schema.

        Tries the primary model with exponential backoff, then the fallback
        model. A schema violation is retried like a transport error, because it
        usually is one: a truncated response and a network blip look identical
        from here.

        The whole thing runs under one wall-clock budget, shared by every
        attempt and both models. The per-attempt timeout alone does not bound
        this — with two models and a retry each it multiplies out to minutes,
        which is long past the point where the caller has given up and the work
        is being done for nobody.

        Args:
            prompt: The complete prompt, already redacted.
            schema: The Pydantic model to validate into.
            purpose: A label for logs and traces, e.g. ``extraction``.

        Returns:
            ModelResult: The parsed answer and its accounting.

        Raises:
            ModelBlockedError: If safety filters refused the content.
            ModelCallError: If every model failed, or the budget ran out.
        """
        chain = [settings.GEMINI_MODEL]
        if settings.GEMINI_FALLBACK_MODEL and settings.GEMINI_FALLBACK_MODEL != settings.GEMINI_MODEL:
            chain.append(settings.GEMINI_FALLBACK_MODEL)

        deadline = time.monotonic() + settings.GEMINI_CALL_BUDGET_SECONDS
        last_error: Optional[Exception] = None

        for index, model_name in enumerate(chain):
            remaining = deadline - time.monotonic()
            if remaining < _MIN_ATTEMPT_SECONDS:
                logger.warning(
                    "gemini_budget_exhausted",
                    purpose=purpose,
                    skipped_model=model_name,
                    budget_seconds=settings.GEMINI_CALL_BUDGET_SECONDS,
                )
                break

            # Each model gets a *share* of what is left, not all of it. Handing
            # the primary the whole budget is what makes a fallback decorative:
            # the case a fallback exists for is the primary hanging, and a
            # hanging primary would spend every second of the budget proving it.
            # The share grows as the chain shortens, so a model that fails fast
            # leaves the next one nearly everything.
            share = remaining / (len(chain) - index)

            try:
                return await self._call_one(prompt, schema, model_name, purpose, share)
            except ModelBlockedError:
                # A refusal is a property of the content, not the model. Trying
                # a second model with the same text wastes a call and a few
                # seconds to arrive at the same answer.
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "gemini_model_exhausted",
                    model=model_name,
                    purpose=purpose,
                    reason=type(exc).__name__,
                )

        logger.error("gemini_all_models_failed", purpose=purpose, models=chain)
        raise ModelCallError(f"no model produced a valid response for {purpose}: {last_error}")

    async def _call_one(
        self,
        prompt: str,
        schema: Type[BaseModel],
        model_name: str,
        purpose: str,
        budget_seconds: float,
    ) -> ModelResult:
        """Call one model, retrying transient failures within a budget.

        Args:
            prompt: The prompt to send.
            schema: Response schema.
            model_name: Which model.
            purpose: Log label.
            budget_seconds: Wall-clock left for this model, retries included.

        Returns:
            ModelResult: The parsed answer.

        Raises:
            ModelBlockedError: On a safety refusal.
            ModelCallError: If the retries or the budget are exhausted.
        """
        model = self._get_model(model_name)
        # `include_raw` keeps the underlying message alongside the parsed object,
        # which is the only way to read usage metadata off a structured call.
        structured = model.with_structured_output(schema, include_raw=True)

        started = time.perf_counter()
        deadline = time.monotonic() + budget_seconds

        try:
            async for attempt in AsyncRetrying(
                # Two stops, because either one alone leaves a hole: the attempt
                # count bounds a fast failure loop, the delay bounds a slow one.
                stop=stop_after_attempt(settings.GEMINI_MAX_RETRIES) | stop_after_delay(budget_seconds),
                wait=wait_exponential(multiplier=1, min=2, max=20),
                # RuntimeError is deliberately absent. `ModelCallError` and
                # `ModelBlockedError` are both RuntimeErrors, and both describe
                # something a second identical call cannot fix — a missing API
                # key, or content the provider refused. Retrying them spent the
                # budget to arrive at the same answer three times over.
                retry=retry_if_exception_type((TimeoutError, ConnectionError, ValueError)),
                reraise=True,
            ):
                with attempt:
                    # The last attempt gets whatever is left rather than a fresh
                    # full timeout, so the budget is a real ceiling and not a
                    # suggestion the final call is free to overshoot.
                    remaining = deadline - time.monotonic()
                    if remaining < _MIN_ATTEMPT_SECONDS:
                        raise ModelCallError(f"{model_name} ran out of budget")

                    response = await asyncio.wait_for(
                        structured.ainvoke([HumanMessage(content=prompt)]),
                        timeout=min(float(settings.GEMINI_TIMEOUT_SECONDS), remaining),
                    )
                    return self._interpret(response, schema, model_name, started, purpose)
        except RetryError as exc:
            raise ModelCallError(f"{model_name} failed after retries") from exc

        raise ModelCallError(f"{model_name} produced no response")

    def _interpret(
        self,
        response: Any,
        schema: Type[BaseModel],
        model_name: str,
        started: float,
        purpose: str,
    ) -> ModelResult:
        """Turn a raw structured-output response into a ``ModelResult``.

        Args:
            response: What ``with_structured_output(include_raw=True)`` returned.
            schema: The expected schema.
            model_name: Which model answered.
            started: ``perf_counter`` value from before the call.
            purpose: Log label.

        Returns:
            ModelResult: The parsed answer and accounting.

        Raises:
            ModelBlockedError: If the response was filtered.
            ValueError: If parsing failed — retryable by the caller.
        """
        latency_ms = int((time.perf_counter() - started) * 1000)

        raw = response.get("raw") if isinstance(response, dict) else None
        parsed = response.get("parsed") if isinstance(response, dict) else response
        parsing_error = response.get("parsing_error") if isinstance(response, dict) else None

        finish_reason = ""
        if raw is not None:
            metadata = getattr(raw, "response_metadata", {}) or {}
            finish_reason = str(metadata.get("finish_reason", "")).upper()

        if finish_reason in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"}:
            logger.error("gemini_content_blocked", model=model_name, purpose=purpose, reason=finish_reason)
            raise ModelBlockedError(
                "El proveedor del modelo rechazó el contenido del documento. "
                "Revise el documento y, si es legítimo, repórtelo al equipo técnico."
            )

        if finish_reason == "MAX_TOKENS":
            # Truncated JSON never parses. Saying so plainly beats a generic
            # "invalid response", because the fix is a config change.
            raise ValueError("response truncated at max_output_tokens; raise GEMINI_MAX_OUTPUT_TOKENS")

        if parsed is None or parsing_error is not None:
            raise ValueError(f"model output did not match {schema.__name__}: {parsing_error}")

        input_tokens, output_tokens = self._read_usage(raw)

        logger.info(
            "gemini_call_succeeded",
            model=model_name,
            purpose=purpose,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        return ModelResult(
            parsed=parsed,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _read_usage(raw: Any) -> tuple[int, int]:
        """Read token counts off a response, tolerating provider differences.

        Args:
            raw: The underlying message, or None.

        Returns:
            tuple: ``(input_tokens, output_tokens)``; zeros when unavailable.
            Missing accounting is not worth failing an otherwise good analysis.
        """
        if raw is None:
            return 0, 0

        usage = getattr(raw, "usage_metadata", None)
        if isinstance(usage, dict):
            return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))

        metadata = getattr(raw, "response_metadata", {}) or {}
        nested = metadata.get("usage_metadata") or metadata.get("token_usage") or {}
        if isinstance(nested, dict):
            return (
                int(nested.get("prompt_token_count", nested.get("prompt_tokens", 0))),
                int(nested.get("candidates_token_count", nested.get("completion_tokens", 0))),
            )

        return 0, 0


gemini_service = GeminiService()
