import path from "node:path";

import { gitStatus } from "./commands.js";
import { latestMarkdown, readText } from "./files.js";


async function snippets(files, maxChars = 600) {
  const output = [];
  for (const file of files) {
    try {
      const text = await readText(file.absolute);
      output.push(`${file.relative}\n${text.slice(0, maxChars)}`);
    } catch {
      output.push(`${file.relative}\nUnavailable`);
    }
  }
  return output;
}

export async function loadMapPlatformContext(config) {
  const dataRoot = path.join(config.mcpServerRoot, "data");
  const tasks = await latestMarkdown(path.join(dataRoot, "map-platform-tasks"), 8);
  const proposals = await latestMarkdown(path.join(dataRoot, "map-platform-patch-proposals"), 8);
  const implementationResults = await latestMarkdown(path.join(dataRoot, "map-platform-implementation-results"), 8);
  const agentRuns = await latestMarkdown(path.join(dataRoot, "agent-runs"), 8);
  const feedbackFiles = await latestMarkdown(path.join(dataRoot, "user-feedback"), 3);
  const dailyReports = await latestMarkdown(path.join(dataRoot, "daily-reports"), 3);
  const strategyFiles = await latestMarkdown(path.join(config.hostStrategyRoot, "docs"), 8);

  return {
    dataRoot,
    tasks,
    proposals,
    implementationResults,
    agentRuns,
    feedbackFiles,
    dailyReports,
    strategyFiles,
    feedbackSnippets: await snippets(feedbackFiles),
    strategySnippets: [
      ...await snippets([{ absolute: path.join(config.hostStrategyRoot, "README.md"), relative: "README.md" }], 1000),
      ...await snippets(strategyFiles, 800),
    ],
    gitStatus: {
      map_platform: await gitStatus(config.mapPlatformRoot),
      "intact-mcp-server": await gitStatus(config.mcpServerRoot),
      "intact-agent-runner": await gitStatus(config.agentRunnerRoot),
    },
  };
}
