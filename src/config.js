import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";


export async function loadConfig() {
  const root = process.env.AGENT_RUNNER_ROOT || process.cwd();
  const configPath = path.join(root, "config", "runner.config.json");
  const raw = JSON.parse(await readFile(configPath, "utf8"));
  return {
    ...raw,
    agentRunnerRoot: root,
    mcpServerRoot: process.env.MCP_SERVER_ROOT || raw.mcpServerRoot,
    mapPlatformRoot: process.env.MAP_PLATFORM_ROOT || raw.mapPlatformRoot,
    llmProvider: process.env.LLM_PROVIDER || raw.llmProvider || "none",
    automationId: process.env.AUTOMATION_ID || raw.defaultAutomationId,
  };
}
