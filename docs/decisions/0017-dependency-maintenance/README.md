# Dependency-maintenance governance

Dependabot pull requests are trusted, narrowly scoped maintenance events created
by GitHub. They do not represent a study, experiment, replication, challenge, or
human methodology contribution and therefore cannot carry an approved Atlas
contribution manifest.

The approval workflow skips only pull requests whose exact GitHub author login is
`dependabot[bot]`. All non-draft human pull requests continue through the
schema-backed proposal checker, which still checks out and executes code solely
from the trusted default branch.

Dependency review, lock validation, Python checks, frontend checks, and browser
tests remain responsible for deciding whether an automated update is compatible.
