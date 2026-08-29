# Atlas evidence explorer

The explorer is a static React/TypeScript/Cytoscape application. It reads only generated JSON beneath
`build/atlas`; no browser code writes canonical evidence and no backend service is required.

```bash
uv run atlas graph build --all
npm run dev --prefix site
```

The development URL uses the same project base path as GitHub Pages:
`/llm-inference-optimization-atlas/`. Production builds copy global and per-study graph projections into
`build/site/data/` and create stable `studies/<study>/v1/` entry routes.

The default Story view follows workload-to-decision paths and hides external
sources until they are requested through search or details. Bottleneck,
Optimization, Evidence, Deployment, and All expose progressively different
projections of the same canonical graph.

Run `npm run test --prefix site` for component tests and `npm run test:e2e --prefix site` for Chromium
desktop/mobile navigation and accessibility checks.
