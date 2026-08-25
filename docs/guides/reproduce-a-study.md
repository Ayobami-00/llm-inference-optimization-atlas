# Reproduce a real-model study

Reproduction is intentionally split into read-only validation, explicit artifact
preparation, local execution, draft inspection, and immutable promotion.

## 1. Verify the repository and host

```bash
make setup
uv run atlas doctor
uv run atlas validate --all --strict
uv run atlas execution list S001-cpu-interactive-chat
```

`doctor` is read-only. Validation does not download a model. Confirm that the
study supports your operating system and hardware; V1 directly supports macOS
ARM64 and Linux CPU, with Windows through WSL2 or Docker.

## 2. Prepare declared artifacts

```bash
uv run atlas execution prepare S001-cpu-interactive-chat transformers-cpu
```

Inspect the displayed model/runtime artifact names, byte sizes, licenses, and
cache status. Preparation is the only normal networked phase. Verified files are
stored once by digest under `.atlas/cache/` and reused across studies.

Bundle names are:

- S001: `transformers-cpu`
- S002: `llama-cpp-cpu-server`
- S003: `docker-cpu-pipeline`

## 3. Run quick, then full

```bash
uv run atlas execution run S001-cpu-interactive-chat transformers-cpu --profile quick
uv run atlas execution run S001-cpu-interactive-chat transformers-cpu --profile full
```

Quick proves the local path with reduced requests and one replicate. It is not
accepted evidence. Full executes the preregistered matrix with three replicates.
The command invokes start/run/destroy lifecycle hooks and cleans up on normal
failure or interruption. Drafts and failure records remain under `.atlas/work/`.

## 4. Validate each draft

Locate the timestamped full-profile directory printed by the command. Validate
each `runs/R####` directory:

```bash
uv run atlas evidence validate .atlas/work/<study>/<bundle>/<timestamp>/runs/R####
```

This checks the run record, environment and artifact manifests, SHA-256 manifest,
quality output, response JSONL, summary metrics, and actual Arrow schemas/units in
`requests.parquet` and `samples.parquet`.

Do not promote a quick, failed, incomplete, quality-invalid, or provenance-invalid
run. Never choose an ID that already exists.

## 5. Promote and compare

```bash
uv run atlas evidence promote <draft-run-directory> --run-id R####
uv run atlas compare E####
```

Promotion copies a validated draft into the owning experiment and refuses to
overwrite accepted evidence. Comparison requires at least three eligible baseline
and candidate runs, checks compatibility, and emits deterministic paired-bootstrap
effects. Review the generated comparison before authoring a finding.

## 6. Validate interpretation and graph

```bash
uv run atlas finding validate studies/<study>/v1/findings/F####.yaml
uv run atlas decision validate studies/<study>/v1/decisions/DEC####.yaml
uv run atlas validate --all --strict
uv run atlas graph build --all
uv run atlas site build
```

Report the exact revision and hardware. A local result may differ from committed
evidence without invalidating either result; create a replication proposal when
the hardware, runtime, model, or workload transfer axis changes.

## Cache and cleanup

```bash
uv run atlas cache inspect
uv run atlas execution destroy <study> <bundle>
uv run atlas cache prune
```

Destroy is idempotent. Cache prune removes only recoverable ignored artifacts and
asks for confirmation. It never deletes accepted evidence.
