import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";


export async function readText(filePath) {
  return readFile(filePath, "utf8");
}

export async function writeText(filePath, content) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, content, "utf8");
}

export async function listMarkdown(root) {
  if (!existsSync(root)) return [];
  const results = [];
  async function walk(current) {
    const entries = await readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      const absolute = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === ".git" || entry.name === "node_modules") continue;
        await walk(absolute);
      } else if (entry.isFile() && entry.name.endsWith(".md")) {
        const info = await stat(absolute);
        results.push({
          absolute,
          relative: path.relative(root, absolute),
          mtimeMs: info.mtimeMs,
        });
      }
    }
  }
  await walk(root);
  return results.sort((a, b) => a.relative.localeCompare(b.relative));
}

export async function latestMarkdown(root, limit = 5) {
  const files = await listMarkdown(root);
  return files.sort((a, b) => b.mtimeMs - a.mtimeMs).slice(0, limit);
}
