import path from "node:path";

import { chooseAgent, loadMapPlatformAgents } from "./agents.js";
import { loadMapPlatformContext } from "./context.js";
import { getProvider } from "./llm.js";
import { writeAgentRun } from "./run-log.js";


export async function planMapPlatform(config) {
  const agents = await loadMapPlatformAgents(config);
  const context = await loadMapPlatformContext(config);
  const selectedAgent = chooseAgent(context);
  const selectedSpec = agents.find((agent) => agent.slug === selectedAgent);

  return {
    product: "map-platform",
    selectedAgent,
    selectedSpec,
    agents,
    context,
    recommendedFocus: recommendFocus(selectedAgent, context),
  };
}

function recommendFocus(selectedAgent, context) {
  if (selectedAgent === "routing-tiles-agent") {
    return "Continue custom router work with graph artifact format, OSM extract parsing, or route QA.";
  }
  if (selectedAgent === "frontend-ux-agent") {
    return "Implement or refine the Place Detail Panel so the dev UI reflects local discovery progress.";
  }
  if (selectedAgent === "qa-evaluation-agent") {
    return "Verify current dev services, test artifacts, and blocked scheduled iterations.";
  }
  return "Select the highest-value unblocked task from the task/proposal queue.";
}

export async function runMapPlatform(config, { dryRun = false } = {}) {
  const plan = await planMapPlatform(config);
  const provider = getProvider(config);
  const completion = await provider.complete({ plan });
  const inputsRead = [
    "data/agent-specs/map-platform/",
    "data/map-platform-tasks/",
    "data/map-platform-patch-proposals/",
    "data/map-platform-implementation-results/",
    "data/agent-runs/",
    "data/user-feedback/",
    "map_platform git/repo context",
  ];

  const run = {
    agent: plan.selectedAgent,
    automationId: config.automationId,
    product: "map-platform",
    status: "completed",
    nextRecommendedAgent: plan.selectedAgent,
    summary: dryRun
      ? `Planned next map-platform run for ${plan.selectedAgent}: ${plan.recommendedFocus}`
      : `Ran ${plan.selectedAgent} in ${provider.name} mode. ${completion.text}`,
    inputsRead,
    tasksConsidered: plan.context.tasks.map((task) => path.relative(config.mcpServerRoot, task.absolute)),
    changesMade: dryRun ? ["None; plan-only run"] : ["None; provider mode did not modify repository files"],
    artifactsWritten: [],
    verification: dryRun ? ["Plan generation completed"] : ["Agent runner completed without throwing"],
    deferred: [
      "Direct MCP stdio tool-calling from runner",
      "LLM-backed code implementation provider",
      "Dashboard UI for agent run inspection",
    ],
    blockers: provider.name === "none" ? ["No LLM provider configured; running deterministic local orchestration only"] : [],
  };
  const runPath = await writeAgentRun(config, run);
  return {
    ...run,
    runPath,
  };
}
