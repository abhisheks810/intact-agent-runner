import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const fixtureRoot = path.join(root, "test", "fixtures");

function run(args, env = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn("node", ["src/cli.js", ...args], {
      cwd: root,
      env: {
        ...process.env,
        AGENT_RUNNER_ROOT: root,
        MCP_SERVER_ROOT: path.join(fixtureRoot, "mcp"),
        MAP_PLATFORM_ROOT: root,
        HOST_STRATEGY_ROOT: path.join(fixtureRoot, "host_strategy"),
        LLM_PROVIDER: "none",
        ...env,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("close", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(stderr || `Command failed with ${code}`));
    });
  });
}

const plan = await run(["plan", "--product", "map-platform"]);
if (!plan.stdout.includes("selectedAgent")) {
  throw new Error("plan output missing selectedAgent");
}

const result = await run(["run", "--product", "map-platform"]);
if (!result.stdout.includes("runPath")) {
  throw new Error("run output missing runPath");
}

try {
  await run(["run", "--product", "map-platform"], {
    LLM_PROVIDER: "openai",
    OPENAI_API_KEY: "",
  });
  throw new Error("openai mode without key unexpectedly passed");
} catch (error) {
  if (!String(error.message).includes("OPENAI_API_KEY is required")) {
    throw error;
  }
}

console.log("smoke test passed");
