# September 2026 dependency refresh

The nine Dependabot proposals opened on 5 September are evaluated as one resolved
dependency graph. The Python updates share `uv.lock`, while the frontend updates
share `site/package-lock.json`; validating the final graph avoids lockfile conflict
churn and catches compatibility problems that isolated branches cannot represent.

React and ReactDOM move together from 19.1.1 to 19.2.8. Their separate Dependabot
branches each paired one new runtime package with one old runtime package and failed
the explorer job. The coordinated update keeps the runtime and declaration packages
aligned.

Cytoscape moves from 3.33.1 to 3.34.2. Cytoscape now publishes its own TypeScript
declarations, so the deprecated `@types/cytoscape` stub is removed instead of kept as
a redundant direct dependency.

The remaining updates are:

- Typer 0.27.1 to 0.27.2.
- Ruff 0.16.4 to 0.16.5.
- Hypothesis 6.165.10 to 6.167.1.
- types-psutil 7.2.2.20260518 to 7.2.2.20260827.
- Testing Library React 16.3.0 to 16.3.3.
- Node types 24.3.0 to 26.4.1.
- React types 19.1.10 to 19.2.18.
- ReactDOM types 19.1.7 to 19.2.5.

No canonical schema, ontology entry, accepted evidence, study runtime, model pin, or
public Atlas command changes. Model execution is not required for this maintenance
boundary.
