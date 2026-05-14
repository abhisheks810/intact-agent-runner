from __future__ import annotations

from pathlib import Path
import re

from .files import list_markdown, read_text


KNOWN_SLUGS = [
    "map-product-strategist",
    "geo-data-agent",
    "backend-api-agent",
    "frontend-ux-agent",
    "accessibility-layer-agent",
    "routing-tiles-agent",
    "qa-evaluation-agent",
    "platform-infra-agent",
]


def slug_from_spec_path(relative_path: str) -> str:
    base = Path(relative_path).stem
    return re.sub(r"^\d+-", "", base)


def load_map_platform_agents(config) -> list[dict]:
    root = Path(config.mcp_server_root) / "data" / "agent-specs" / "map-platform"
    agents = []
    for file in list_markdown(root):
        slug = slug_from_spec_path(file["relative"])
        agents.append({
            "slug": slug,
            "path": file["absolute"],
            "relativePath": str(Path(file["absolute"]).relative_to(config.mcp_server_root)),
            "spec": read_text(file["absolute"]),
        })
    return sorted(
        agents,
        key=lambda agent: KNOWN_SLUGS.index(agent["slug"]) if agent["slug"] in KNOWN_SLUGS else 999,
    )


def choose_agent(context: dict) -> str:
    text = "\n".join(
        [item["relative"] for item in context["tasks"]]
        + [item["relative"] for item in context["proposals"]]
        + context["feedbackSnippets"]
    ).lower()

    if "custom-router" in text or "routing" in text or "osm" in text:
        return "routing-tiles-agent"
    if "place detail" in text or "frontend" in text or "ui" in text:
        return "frontend-ux-agent"
    if "accessibility" in text or "sign language" in text:
        return "accessibility-layer-agent"
    if "geocode" in text or "place" in text or "poi" in text:
        return "geo-data-agent"
    return "qa-evaluation-agent"
