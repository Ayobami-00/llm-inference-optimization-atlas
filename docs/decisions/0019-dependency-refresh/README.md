# Coordinated dependency refresh

Python, frontend, and GitHub Actions maintenance updates are evaluated as one
resolved dependency graph. This avoids merging mutually conflicting lockfile
updates and allows coupled majors such as Vite and its React plugin to move
together.

The Vitest component test checks the stable media-path suffix because Vitest's
synthetic `import.meta.env.BASE_URL` is not a deployment contract. The Playwright
suite continues to assert the exact GitHub Pages project path in a built site.

Transformers 5 is intentionally excluded. Accepted S001 and S003 evidence,
`RT001`, Docker execution, and bundle requirements are pinned to Transformers
4.57.6. A new major requires a separately approved runtime revision and real-model
reproduction before it can become the default installation.
