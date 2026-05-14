import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";


export async function loadConfig() {
  const root = process.env.AGENT_RUNNER_ROOT || process.cwd();
  const configPath = path.join(root, "config", "runner.config.json");
  const raw = JSON.parse(await readFile(configPath, "utf8"));
  const mcpServerRoot = process.env.MCP_SERVER_ROOT || raw.mcpServerRoot;
  const mapPlatformRoot = process.env.MAP_PLATFORM_ROOT || raw.mapPlatformRoot;
  const hostStrategyRoot = process.env.HOST_STRATEGY_ROOT || raw.hostStrategyRoot || "/Users/abhisheksrivastava/host_strategy";
  return {
    ...raw,
    agentRunnerRoot: root,
    mcpServerRoot,
    mapPlatformRoot,
    hostStrategyRoot,
    llmProvider: process.env.LLM_PROVIDER || raw.llmProvider || "none",
    openaiModel: process.env.OPENAI_MODEL || raw.openaiModel || "gpt-5.2",
    automationId: process.env.AUTOMATION_ID || raw.defaultAutomationId,
    commitAndPush: process.env.COMMIT_AND_PUSH
      ? process.env.COMMIT_AND_PUSH === "1"
      : raw.commitAndPush !== false,
    allowedRepoRoots: {
      map_platform: mapPlatformRoot,
      "intact-mcp-server": mcpServerRoot,
      "intact-agent-runner": root,
    },
  };
}
