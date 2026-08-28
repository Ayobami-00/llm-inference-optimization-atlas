import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const siteRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(siteRoot, "..");
const atlasBuild = path.join(repositoryRoot, "build", "atlas");
const outputRoot = path.join(repositoryRoot, "build", "site");
const projectBase = "/llm-inference-optimization-atlas/";

function atlasData(): Plugin {
  return {
    name: "atlas-data",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const prefix = `${projectBase}data/`;
        if (!request.url?.startsWith(prefix)) return next();
        const relative = decodeURIComponent(request.url.slice(prefix.length).split("?", 1)[0]);
        const filePath = path.resolve(atlasBuild, relative);
        if (!filePath.startsWith(`${path.resolve(atlasBuild)}${path.sep}`)) {
          response.statusCode = 403;
          response.end("Forbidden");
          return;
        }
        if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
          response.statusCode = 404;
          response.end("Not found");
          return;
        }
        response.setHeader(
          "Content-Type",
          filePath.endsWith(".json") ? "application/json" : "text/plain",
        );
        fs.createReadStream(filePath).pipe(response);
      });
    },
    closeBundle() {
      if (!fs.existsSync(path.join(atlasBuild, "manifest.json"))) {
        throw new Error("No compiled graph found. Run `atlas graph build --all` first.");
      }
      fs.cpSync(atlasBuild, path.join(outputRoot, "data"), { recursive: true });
      const index = fs.readFileSync(path.join(outputRoot, "index.html"), "utf8");
      const studiesRoot = path.join(atlasBuild, "studies");
      if (fs.existsSync(studiesRoot)) {
        for (const study of fs.readdirSync(studiesRoot)) {
          const versions = fs.readdirSync(path.join(studiesRoot, study));
          for (const version of versions) {
            const route = path.join(outputRoot, "studies", study, version);
            fs.mkdirSync(route, { recursive: true });
            fs.writeFileSync(path.join(route, "index.html"), index);
          }
        }
      }
    },
  };
}

export default defineConfig({
  base: projectBase,
  plugins: [react(), atlasData()],
  build: {
    outDir: outputRoot,
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
          cytoscape: ["cytoscape"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
