// Renders the review screenshots from scene.json (written by tools/export-scene.luau).
//   node render.mjs [outDir] [viewId...]
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { extname, join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(process.argv[2] ?? join(here, "../../screenshots"));
const only = process.argv.slice(3);
const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json" };

const server = createServer(async (req, res) => {
  const path = join(here, decodeURIComponent(new URL(req.url, "http://x").pathname));
  try {
    const body = await readFile(path);
    res.writeHead(200, { "Content-Type": types[extname(path)] ?? "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
const base = `http://127.0.0.1:${server.address().port}/index.html`;

const scene = JSON.parse(await readFile(join(here, "scene.json"), "utf8"));
await mkdir(outDir, { recursive: true });

const executablePath = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({
  executablePath,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});
try {
  for (const view of scene.views) {
    if (only.length && !only.includes(view.id)) continue;
    const page = await browser.newPage({ viewport: { width: view.width ?? 1600, height: view.height ?? 900 } });
    page.on("pageerror", (err) => console.error(view.id, err.message));
    await page.goto(`${base}?view=${view.id}`);
    await page.waitForFunction(() => window.__rendered === true, null, { timeout: 180000 });
    const file = join(outDir, `${view.id}.png`);
    await page.screenshot({ path: file });
    console.log("wrote", file);
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
}
