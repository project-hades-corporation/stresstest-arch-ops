"""Pydantic schemas used by topology and agent workflows."""

from typing import Any

from pydantic import BaseModel, Field


class TopologyNode(BaseModel):
    id: str = ""
    label: str = ""
    type: str = "service"
    capacity_rps: int = 0


class TopologyEdge(BaseModel):
    source: str = ""
    target: str = ""
    protocol: str = "http"
    latency_ms: int = 0


class CanonicalTopology(BaseModel):
    """Canonical representation of a system-under-test topology."""

    nodes: list[TopologyNode] = Field(default_factory=list)
    edges: list[TopologyEdge] = Field(default_factory=list)


class AnnotatedTopology(BaseModel):
    """Chaos-annotated topology with per-node status and root causes."""

    topology: CanonicalTopology = Field(default_factory=CanonicalTopology)
    statuses: dict[str, str] = Field(default_factory=dict)
    root_causes: dict[str, str] = Field(default_factory=dict)
    analysis: str = ""
    scenario: str = ""


class FixPlan(BaseModel):
    """Proposed topology mutations to resolve failure points."""

    original: CanonicalTopology = Field(default_factory=CanonicalTopology)
    mutations: list[dict[str, Any]] = Field(default_factory=list)
    rationale: str = ""


class BlueprintPlan(BaseModel):
    """Production blueprint: Terraform, Docker Compose, and setup commands."""

    topology: CanonicalTopology = Field(default_factory=CanonicalTopology)
    terraform_main: str = ""
    terraform_variables: str = ""
    docker_compose: str = ""
    setup_commands: list[str] = Field(default_factory=list)
    notes: str = ""
