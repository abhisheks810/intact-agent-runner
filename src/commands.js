import { spawn } from "node:child_process";


export function runCommand(command, args, {
  cwd,
  env = {},
  input = undefined,
  timeoutMs = 120000,
} = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd,
      env: { ...process.env, ...env },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
    }, timeoutMs);

    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("close", (code, signal) => {
      clearTimeout(timer);
      resolve({
        command: [command, ...args].join(" "),
        cwd,
        code,
        signal,
        timedOut,
        stdout,
        stderr,
        ok: code === 0 && !timedOut,
      });
    });

    if (input) child.stdin.write(input);
    child.stdin.end();
  });
}

export async function gitStatus(repoRoot) {
  const result = await runCommand("git", ["status", "--short", "--branch"], {
    cwd: repoRoot,
    timeoutMs: 30000,
  });
  return result;
}

export function commandSummary(result) {
  const parts = [`$ ${result.command}`];
  if (result.cwd) parts.push(`cwd: ${result.cwd}`);
  parts.push(`exit: ${result.timedOut ? "timeout" : result.code}`);
  if (result.stdout.trim()) parts.push(`stdout:\n${result.stdout.trim()}`);
  if (result.stderr.trim()) parts.push(`stderr:\n${result.stderr.trim()}`);
  return parts.join("\n");
}
