"""Governance bridge for the control surface.

This is where the User/Control plane and the Governance/Radar plane actually
merge at the *enforcement* level (not just the dashboard). Each logical control
agent is mirrored as a governed entry in the shared radar registry, and
write-capable runs are gated through the SAME policy the radar plane uses
(quarantine + failure-budget + autonomy ladder). Outcomes feed back so repeated
failures degrade autonomy.

Because the gateway process imports the module-level ``REGISTRY`` singleton, the
control gate and the mounted radar endpoints (/governance/agents/{id}/signal,
/autonomy, ...) operate on the same state — degrade an agent on either side and
the control gate sees it immediately.
"""
from __future__ import annotations

import logging
import time

from awcp.radar import policy
from awcp.radar.models import AgentEntry
from awcp.radar.store import REGISTRY

logger = logging.getLogger(__name__)


def agent_id(agent_name: str) -> str:
    """Stable governed id for a logical control agent."""
    return f"control:{agent_name}"


def _record(kind: str, aid: str, detail: str = "", **extra) -> None:
    """Append to the radar evidence/audit trail if available.

    Lazily imported so the standalone control surface neither pays the radar
    import cost at load time nor fails if the radar app can't be imported.
    """
    try:  # pragma: no cover - best-effort audit
        from awcp.radar.api import _record_event
        _record_event(kind, aid, detail, **extra)
    except Exception:
        pass


def ensure_governed(agent_name: str, runtime: str = "") -> AgentEntry:
    """Get-or-create a governed registry entry for a control agent.

    Registered as already-instrumented (telemetry + feature flags + policy
    callbacks) so onboarding admits it ``active`` instead of quarantining it.
    Refreshes liveness on every call so the registry's self-entry pruning does
    not age out an actively-used control agent.
    """
    aid = agent_id(agent_name)
    existing = REGISTRY.get(aid)
    if existing:
        REGISTRY.patch(aid, last_seen=time.time(), alive=True)
        return existing

    entry = AgentEntry(
        id=aid,
        name=agent_name,
        kind="agent_framework",
        source="self",
        runtime=runtime or "ollama",
        owner="control-plane",
        telemetry_enabled=True,
        feature_flags={"governed": True},
        policy_callbacks=["control.gate"],
        status="active",
        autonomy_profile="active",
        risk="medium",
    )
    saved = REGISTRY.register(entry)
    logger.info("governance.ensure_governed registered agent_id=%s", aid)
    return saved


def gate(agent_name: str, action: str, is_write: bool = True) -> dict:
    """Evaluate the write-action gate for a control agent before execution."""
    entry = ensure_governed(agent_name)
    decision = policy.evaluate_action(entry, action=action, is_write=is_write)
    logger.info(
        "governance.gate agent=%s action=%r decision=%s mode=%s",
        agent_name, action, decision["decision"], decision["mode"],
    )
    _record(
        "gate", entry.id,
        f"{decision['decision']} ({decision['mode']})",
        action=action, source="control",
    )
    return decision


def report(agent_name: str, ok: bool, reason: str = "") -> dict:
    """Feed an execution outcome back into the degradation ladder."""
    entry = ensure_governed(agent_name)
    result = policy.apply_signal(entry, ok=ok, reason=reason)
    REGISTRY.patch(entry.id, **result["patch"])
    logger.info(
        "governance.report agent=%s ok=%s degraded=%s -> %s",
        agent_name, ok, result["degraded"], result["patch"].get("autonomy_profile"),
    )
    return result
