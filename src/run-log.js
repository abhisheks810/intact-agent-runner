import path from "node:path";

import { writeText } from "./files.js";


function stamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function list(items, fallback = "None") {
  return Array.isArray(items) && items.length
    ? items.map((item) => `- ${item}`).join("\n")
    : `- ${fallback}`;
}

function isWritePermissionError(error) {
  return (
    error &&
    typeof error === "object" &&
    (error.code === "EACCES" || error.code === "EPERM" || error.code === "EROFS")
  );
}

export async function writeAgentRun(config, run) {
  const fileName = `${stamp()}-${run.agent}.md`;
  const primaryPath = path.join(config.mcpServerRoot, "data", "agent-runs", fileName);
  const fallbackPath = path.join(config.agentRunnerRoot, "data", "agent-runs", fileName);
  const content = [
    `# Agent Run: ${run.agent}`,
    "",
    `Created: ${new Date().toISOString()}`,
    `Agent: ${run.agent}`,
    `Automation: ${run.automationId}`,
    `Product: ${run.product}`,
    `Status: ${run.status}`,
    run.nextRecommendedAgent ? `Next recommended agent: ${run.nextRecommendedAgent}` : "Next recommended agent: TBD",
    "",
    "## Summary",
    "",
    run.summary,
    "",
    "## Inputs Read",
    "",
    list(run.inputsRead),
    "",
    "## Tasks Considered",
    "",
    list(run.tasksConsidered),
    "",
    "## Changes Made",
    "",
    list(run.changesMade),
    "",
    "## Artifacts Written",
    "",
    list(run.artifactsWritten),
    "",
    "## Verification",
    "",
    list(run.verification, "Not run"),
    "",
    "## Deferred",
    "",
    list(run.deferred),
    "",
    "## Blockers",
    "",
    list(run.blockers),
    "",
  ].join("\n");

  try {
    await writeText(primaryPath, content);
    return primaryPath;
  } catch (error) {
    if (!isWritePermissionError(error)) throw error;
  }

  await writeText(fallbackPath, content);
  return fallbackPath;
}
