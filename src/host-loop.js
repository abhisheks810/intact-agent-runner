import { commandSummary, gitStatus, runCommand } from "./commands.js";
import {
  applyAgentPatch,
  buildDevelopmentPrompt,
  developmentInstructions,
  finalizeRepos,
  parseAgentDecision,
  runVerification,
} from "./development-agent.js";
import { getProvider } from "./llm.js";
import { planMapPlatform } from "./runner.js";
import { writeAgentRun, writeImplementationResult } from "./run-log.js";


function dirtyLines(statusOutput) {
  return statusOutput
    .split("\n")
    .filter((line) => line && !line.startsWith("##"));
}

async function allReposClean(config) {
  const results = [];
  const blockers = [];
  for (const [name, root] of Object.entries(config.allowedRepoRoots)) {
    const result = await gitStatus(root);
    results.push(`${name}\n${result.stdout || result.stderr}`);
    const dirty = dirtyLines(result.stdout);
    if (!result.ok) blockers.push(`${name}: git status failed`);
    if (dirty.length) blockers.push(`${name}: repo is not clean\n${dirty.join("\n")}`);
  }
  return { clean: blockers.length === 0, results, blockers };
}

export async function runHostMapPlatformLoop(config) {
  const statusCheck = await allReposClean(config);
  if (!statusCheck.clean) {
    return writeFailure(config, {
      agent: "platform-infra-agent",
      status: "failed",
      summary: "Host runner stopped before preflight because one or more repos were dirty.",
      inputsRead: ["git status for all allowed repos"],
      verification: statusCheck.results,
      blockers: statusCheck.blockers,
    });
  }

  const preflight = await runCommand("bash", ["./scripts/loop-preflight.sh", "--require-clean"], {
    cwd: config.mapPlatformRoot,
    timeoutMs: 120000,
  });
  if (!preflight.ok) {
    return writeFailure(config, {
      agent: "platform-infra-agent",
      status: "failed",
      summary: "Host runner stopped at the mandatory map-platform preflight gate.",
      inputsRead: [
        "git status for all allowed repos",
        "/Users/abhisheksrivastava/map_platform/scripts/loop-preflight.sh",
      ],
      verification: [commandSummary(preflight)],
      blockers: [
        "Mandatory loop preflight failed; no development work was attempted.",
        "Recovery: verify host DNS/network for github.com, rerun preflight, then rerun this host loop.",
      ],
    });
  }

  const plan = await planMapPlatform(config);
  const provider = getProvider(config);
  const completion = await provider.complete({
    instructions: developmentInstructions(),
    prompt: buildDevelopmentPrompt(plan, config),
  });
  const decision = provider.name === "none"
    ? {
        agentRole: plan.selectedAgent,
        selectedTask: plan.recommendedFocus,
        targetRepo: "map_platform",
        summary: "Dry-run provider selected the next task but did not propose a patch.",
        unifiedDiff: "",
        changedFiles: [],
        verification: ["Plan generation completed"],
        commitMessage: "agent-run: map-platform host iteration",
        deferred: ["Enable LLM_PROVIDER=openai for implementation patches"],
        blockers: ["No LLM provider configured; no development patch was generated"],
      }
    : parseAgentDecision(completion.text);

  const patch = await applyAgentPatch(config, decision);
  const verification = patch.applied
    ? await runVerification(config, decision)
    : { ok: decision.unifiedDiff.trim() ? false : true, results: [patch.summary] };
  const targetFinalization = patch.applied && verification.ok
    ? await finalizeRepos(config, decision.commitMessage, { only: [decision.targetRepo] })
    : { ok: true, results: ["No finalization attempted because no verified patch was applied."] };

  const status = patch.applied && verification.ok && targetFinalization.ok && decision.blockers.length === 0
    ? "completed"
    : "completed_with_blockers";
  const run = {
    agent: decision.agentRole,
    automationId: config.automationId,
    product: "map-platform",
    status,
    nextRecommendedAgent: decision.agentRole,
    summary: decision.summary,
    inputsRead: [
      "host_strategy README.md and docs/",
      "data/agent-specs/map-platform/",
      "data/map-platform-tasks/",
      "data/map-platform-patch-proposals/",
      "data/map-platform-implementation-results/",
      "data/agent-runs/",
      "data/user-feedback/",
      "git status for all allowed repos",
      "canonical loop preflight",
    ],
    tasksConsidered: plan.context.tasks.map((task) => task.relative),
    changesMade: patch.applied ? decision.changedFiles : ["No repository files changed"],
    artifactsWritten: ["Agent-run artifact pending", "Implementation-result artifact pending"],
    verification: [
      commandSummary(preflight),
      ...(patch.commands || []),
      ...verification.results,
      ...targetFinalization.results,
    ],
    deferred: decision.deferred,
    blockers: [
      ...decision.blockers,
      ...(patch.applied ? [] : [patch.summary]),
      ...(verification.ok ? [] : ["Verification failed"]),
      ...(targetFinalization.ok ? [] : ["Target repository Git finalization failed"]),
    ].filter(Boolean),
  };
  const runPath = await writeAgentRun(config, run);
  const resultPath = await writeImplementationResult(config, {
    slug: "host-map-platform-loop",
    agent: decision.agentRole,
    title: "host map-platform loop",
    status,
    summary: decision.summary,
    verification: run.verification,
    gitFinalization: targetFinalization.results,
    blockers: run.blockers,
  });
  const artifactFinalization = await finalizeRepos(
    config,
    `agent-run: record ${decision.agentRole} host loop artifacts`,
    { skip: [decision.targetRepo] },
  );
  return {
    ...run,
    runPath,
    resultPath,
    artifactFinalization,
  };
}

async function writeFailure(config, partial) {
  const run = {
    automationId: config.automationId,
    product: "map-platform",
    nextRecommendedAgent: partial.agent,
    tasksConsidered: [],
    changesMade: ["None"],
    artifactsWritten: [],
    deferred: ["Development work deferred until host-runner gate passes"],
    ...partial,
  };
  const runPath = await writeAgentRun(config, run);
  const resultPath = await writeImplementationResult(config, {
    slug: "host-map-platform-loop-failed",
    agent: run.agent,
    title: "host map-platform loop failed",
    status: run.status,
    summary: run.summary,
    verification: run.verification,
    gitFinalization: ["Not attempted"],
    blockers: run.blockers,
  });
  const artifactFinalization = await finalizeRepos(
    config,
    `agent-run: record failed ${run.agent} host loop artifacts`,
    { only: ["intact-mcp-server"] },
  );
  return {
    ...run,
    runPath,
    resultPath,
    artifactFinalization,
  };
}
