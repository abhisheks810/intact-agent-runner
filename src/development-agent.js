import { commandSummary, runCommand } from "./commands.js";


const allowedTargetRepos = new Set(["map_platform", "intact-mcp-server", "intact-agent-runner"]);

export function buildDevelopmentPrompt(plan, config) {
  return [
    "You are the bounded map-platform host-runner development agent.",
    "Pick one small, high-value unblocked task aligned to the org strategy.",
    "Priority order: dev-interface reliability, place detail/local discovery, accessibility metadata, QA/evaluation, custom routing, documentation.",
    "Do not propose production deploys, secrets access, destructive Git operations, or unrelated repo rewrites.",
    "Return only JSON with this shape:",
    JSON.stringify({
      agent_role: plan.selectedAgent,
      selected_task: "short task name",
      target_repo: "map_platform",
      summary: "what the run should do",
      unified_diff: "",
      changed_files: [],
      verification: [],
      commit_message: "agent-run: map-platform host iteration",
      deferred: [],
      blockers: [],
    }, null, 2),
    "",
    "Allowed target_repo values: map_platform, intact-mcp-server, intact-agent-runner.",
    "If no safe implementation is available, set unified_diff to an empty string and explain the blocker.",
    "",
    "Selected agent spec:",
    plan.selectedSpec?.spec || "Unavailable",
    "",
    "Recommended focus:",
    plan.recommendedFocus,
    "",
    "Strategy context:",
    plan.context.strategySnippets.join("\n\n---\n\n"),
    "",
    "Feedback context:",
    plan.context.feedbackSnippets.join("\n\n---\n\n"),
    "",
    "Recent tasks:",
    plan.context.tasks.map((task) => task.relative).join("\n"),
    "",
    "Recent implementation results:",
    plan.context.implementationResults.map((result) => result.relative).join("\n"),
    "",
    "Git status:",
    Object.entries(plan.context.gitStatus)
      .map(([name, result]) => `${name}\n${result.stdout || result.stderr}`)
      .join("\n---\n"),
    "",
    `Commit-and-push finalization is ${config.commitAndPush ? "enabled" : "disabled"}.`,
  ].join("\n");
}

export function developmentInstructions() {
  return [
    "You are a senior development agent operating under a host-runner policy.",
    "You may propose a unified diff only for allowlisted repositories and only for the selected small task.",
    "Keep patches minimal and reviewable.",
    "Do not include markdown fences around JSON.",
  ].join("\n");
}

export function parseAgentDecision(text) {
  try {
    const parsed = JSON.parse(text);
    return normalizeDecision(parsed);
  } catch (error) {
    throw new Error(`Agent response was not valid JSON: ${error.message}\n${text.slice(0, 1200)}`);
  }
}

function normalizeDecision(decision) {
  const targetRepo = decision.target_repo || "map_platform";
  if (!allowedTargetRepos.has(targetRepo)) {
    throw new Error(`Agent selected unsupported target_repo: ${targetRepo}`);
  }
  return {
    agentRole: decision.agent_role || "qa-evaluation-agent",
    selectedTask: decision.selected_task || "Unspecified task",
    targetRepo,
    summary: decision.summary || "No summary returned by agent.",
    unifiedDiff: decision.unified_diff || "",
    changedFiles: Array.isArray(decision.changed_files) ? decision.changed_files : [],
    verification: Array.isArray(decision.verification) ? decision.verification : [],
    commitMessage: decision.commit_message || "agent-run: map-platform host iteration",
    deferred: Array.isArray(decision.deferred) ? decision.deferred : [],
    blockers: Array.isArray(decision.blockers) ? decision.blockers : [],
  };
}

export async function applyAgentPatch(config, decision) {
  if (!decision.unifiedDiff.trim()) {
    return {
      applied: false,
      summary: "No patch proposed by agent.",
      commands: [],
    };
  }

  const repoRoot = config.allowedRepoRoots[decision.targetRepo];
  const check = await runCommand("git", ["apply", "--check", "--whitespace=nowarn", "-"], {
    cwd: repoRoot,
    input: decision.unifiedDiff,
    timeoutMs: 60000,
  });
  if (!check.ok) {
    return {
      applied: false,
      summary: `Patch check failed.\n${commandSummary(check)}`,
      commands: [commandSummary(check)],
    };
  }

  const apply = await runCommand("git", ["apply", "--whitespace=nowarn", "-"], {
    cwd: repoRoot,
    input: decision.unifiedDiff,
    timeoutMs: 60000,
  });
  return {
    applied: apply.ok,
    summary: apply.ok ? "Patch applied." : `Patch apply failed.\n${commandSummary(apply)}`,
    commands: [commandSummary(check), commandSummary(apply)],
  };
}

export async function runVerification(config, decision) {
  const repoRoot = config.allowedRepoRoots[decision.targetRepo];
  const commands = [];
  if (decision.targetRepo === "map_platform") {
    commands.push({
      command: "bash",
      args: ["./scripts/verify.sh"],
      cwd: repoRoot,
      env: { PYTHONPYCACHEPREFIX: "/tmp/map_platform_pycache" },
    });
  } else if (decision.targetRepo === "intact-agent-runner") {
    commands.push({
      command: "npm",
      args: ["test"],
      cwd: repoRoot,
    });
  } else {
    commands.push({
      command: "git",
      args: ["diff", "--check"],
      cwd: repoRoot,
    });
  }

  const results = [];
  for (const item of commands) {
    const result = await runCommand(item.command, item.args, {
      cwd: item.cwd,
      env: item.env,
      timeoutMs: 300000,
    });
    results.push(commandSummary(result));
    if (!result.ok) {
      return { ok: false, results };
    }
  }
  return { ok: true, results };
}

export async function finalizeRepos(config, commitMessage) {
  const results = [];
  for (const [name, repoRoot] of Object.entries(config.allowedRepoRoots)) {
    const status = await runCommand("git", ["status", "--porcelain"], {
      cwd: repoRoot,
      timeoutMs: 30000,
    });
    if (!status.ok) {
      results.push(`${name}: status failed\n${commandSummary(status)}`);
      continue;
    }
    if (!status.stdout.trim()) {
      results.push(`${name}: no changes`);
      continue;
    }

    const add = await runCommand("git", ["add", "--all"], { cwd: repoRoot, timeoutMs: 30000 });
    results.push(`${name}: ${commandSummary(add)}`);
    if (!add.ok) continue;

    const check = await runCommand("git", ["diff", "--cached", "--check"], { cwd: repoRoot, timeoutMs: 30000 });
    results.push(`${name}: ${commandSummary(check)}`);
    if (!check.ok) continue;

    const commit = await runCommand("git", ["commit", "-m", commitMessage], { cwd: repoRoot, timeoutMs: 60000 });
    results.push(`${name}: ${commandSummary(commit)}`);
    if (!commit.ok) continue;

    if (config.commitAndPush) {
      const push = await runCommand("git", ["push", "origin", "main"], { cwd: repoRoot, timeoutMs: 120000 });
      results.push(`${name}: ${commandSummary(push)}`);
      if (!push.ok) {
        return { ok: false, results };
      }
    }
  }
  return { ok: true, results };
}
