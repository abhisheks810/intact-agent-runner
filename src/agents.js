import path from "node:path";

import { listMarkdown, readText } from "./files.js";


const knownSlugs = [
  "map-product-strategist",
  "geo-data-agent",
  "backend-api-agent",
  "frontend-ux-agent",
  "accessibility-layer-agent",
  "routing-tiles-agent",
  "qa-evaluation-agent",
  "platform-infra-agent",
];


function slugFromSpecPath(relativePath) {
  const base = path.basename(relativePath, ".md");
  return base.replace(/^\d+-/, "");
}

export async function loadMapPlatformAgents(config) {
  const root = path.join(config.mcpServerRoot, "data", "agent-specs", "map-platform");
  const files = await listMarkdown(root);
  const agents = [];
  for (const file of files) {
    const slug = slugFromSpecPath(file.relative);
    agents.push({
      slug,
      path: file.absolute,
      relativePath: path.relative(config.mcpServerRoot, file.absolute),
      spec: await readText(file.absolute),
    });
  }
  return agents.sort((a, b) => {
    const ai = knownSlugs.indexOf(a.slug);
    const bi = knownSlugs.indexOf(b.slug);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
}

export function chooseAgent(context) {
  const text = [
    ...context.tasks.map((task) => task.relative),
    ...context.proposals.map((proposal) => proposal.relative),
    ...context.feedbackSnippets,
  ].join("\n").toLowerCase();

  if (text.includes("custom-router") || text.includes("routing") || text.includes("osm")) {
    return "routing-tiles-agent";
  }
  if (text.includes("place detail") || text.includes("frontend") || text.includes("ui")) {
    return "frontend-ux-agent";
  }
  if (text.includes("accessibility") || text.includes("sign language")) {
    return "accessibility-layer-agent";
  }
  if (text.includes("geocode") || text.includes("place") || text.includes("poi")) {
    return "geo-data-agent";
  }
  return "qa-evaluation-agent";
}
