#!/usr/bin/env node
import process from "node:process";

import { loadConfig } from "./config.js";
import { runHostMapPlatformLoop } from "./host-loop.js";
import { planMapPlatform, runMapPlatform } from "./runner.js";


function argValue(name, fallback = undefined) {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  return process.argv[index + 1] || fallback;
}

async function main() {
  const command = process.argv[2] || "run";
  const product = argValue("--product", "map-platform");
  if (product !== "map-platform") {
    throw new Error(`Unsupported product: ${product}`);
  }

  const config = await loadConfig();

  if (command === "plan") {
    const plan = await planMapPlatform(config);
    console.log(JSON.stringify({
      product: plan.product,
      selectedAgent: plan.selectedAgent,
      recommendedFocus: plan.recommendedFocus,
      availableAgents: plan.agents.map((agent) => agent.slug),
      recentTasks: plan.context.tasks.map((task) => task.relative),
    }, null, 2));
    return;
  }

  if (command === "run") {
    const result = await runMapPlatform(config, { dryRun: config.llmProvider === "none" });
    console.log(JSON.stringify({
      agent: result.agent,
      status: result.status,
      runPath: result.runPath,
      summary: result.summary,
      blockers: result.blockers,
    }, null, 2));
    return;
  }

  if (command === "host-run") {
    const result = await runHostMapPlatformLoop(config);
    console.log(JSON.stringify({
      agent: result.agent,
      status: result.status,
      runPath: result.runPath,
      resultPath: result.resultPath,
      summary: result.summary,
      blockers: result.blockers,
    }, null, 2));
    return;
  }

  throw new Error(`Unsupported command: ${command}`);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
