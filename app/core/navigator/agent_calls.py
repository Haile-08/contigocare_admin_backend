"""The one place the navigation agents reach a model.

The handover's agents each built an Anthropic client, called it, stripped a
markdown fence, ``json.loads``-ed the answer, and fell back to a fixed result on
any failure. The fallbacks stay in the agents, exactly as they were. The call
itself lives here, so every agent gets the console's retries, fallback model,
budget and accounting, and so a failure is recorded the same way whichever
agent had it.
"""

from dataclasses import (
    dataclass,
    field,
)
from datetime import date
from typing import (
    Any,
    Optional,
)

from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import navigation_agent_calls_total
from app.services.llm import gemini_service

AGENT_KEYS = ("parser", "planner", "notification", "optimizer", "adherence", "advocate")


def agent_model(agent: str) -> str:
    """The configured model for an agent.

    Args:
        agent: One of :data:`AGENT_KEYS`.

    Returns:
        str: The model id.
    """
    return {
        "parser": settings.AGENT_MODEL_PARSER,
        "planner": settings.AGENT_MODEL_PLANNER,
        "notification": settings.AGENT_MODEL_NOTIFICATION,
        "optimizer": settings.AGENT_MODEL_OPTIMIZER,
        "adherence": settings.AGENT_MODEL_ADHERENCE,
        "advocate": settings.AGENT_MODEL_ADVOCATE,
    }[agent]


@dataclass
class AgentUsage:
    """Accounting for one agent's call.

    Attributes:
        agent: Agent key.
        model_name: Which model answered; empty when the call failed.
        input_tokens: Prompt tokens.
        output_tokens: Completion tokens.
        latency_ms: Time for the call.
        degraded: The call failed and the agent's fallback was used.
    """

    agent: str
    model_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    degraded: bool = False


@dataclass
class AgentContext:
    """What one pipeline run carries between agents.

    Attributes:
        today: The run date. The handover read ``datetime.now()`` in each agent;
            one date passed through keeps a run consistent and testable.
        usage: One entry per model call.
        warnings: Things the coordinator should double-check.
    """

    today: date
    usage: list[AgentUsage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def degraded_agents(self) -> list[str]:
        """Agents whose call failed.

        Returns:
            list[str]: Agent keys, in call order.
        """
        return [usage.agent for usage in self.usage if usage.degraded]

    async def json(self, agent: str, prompt: str, system: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Ask an agent's model for a JSON object.

        Args:
            agent: Agent key.
            prompt: The user prompt.
            system: The system prompt.

        Returns:
            Optional[dict]: The object, or None when the call failed.
        """
        return await self._call(agent, prompt, system, json_mode=True)

    async def text(self, agent: str, prompt: str, system: Optional[str] = None) -> Optional[str]:
        """Ask an agent's model for prose.

        Args:
            agent: Agent key.
            prompt: The user prompt.
            system: The system prompt.

        Returns:
            Optional[str]: The text, or None when the call failed.
        """
        return await self._call(agent, prompt, system, json_mode=False)

    async def _call(self, agent: str, prompt: str, system: Optional[str], json_mode: bool) -> Any:
        """Make one call, absorbing any failure into the agent's fallback.

        Args:
            agent: Agent key.
            prompt: The user prompt.
            system: The system prompt.
            json_mode: JSON object or prose.

        Returns:
            Any: The parsed answer, or None on failure.
        """
        call = gemini_service.json_call if json_mode else gemini_service.text_call
        try:
            result = await call(
                prompt,
                system=system,
                purpose=f"navigation_{agent}",
                model=agent_model(agent),
                timeout_seconds=settings.NAVIGATION_CALL_TIMEOUT_SECONDS,
                budget_seconds=settings.NAVIGATION_CALL_BUDGET_SECONDS,
            )
        except Exception as exc:
            # Blocked content, exhausted retries, JSON the model would not
            # produce: all degrade the same way. The reason type is logged, never
            # the prompt or the response.
            logger.warning("navigation_agent_degraded", agent=agent, reason=type(exc).__name__)
            navigation_agent_calls_total.labels(agent=agent, outcome="degraded").inc()
            self.usage.append(AgentUsage(agent=agent, degraded=True))
            return None

        navigation_agent_calls_total.labels(agent=agent, outcome="ok").inc()
        self.usage.append(
            AgentUsage(
                agent=agent,
                model_name=result.model_name,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
            )
        )
        return result.parsed
