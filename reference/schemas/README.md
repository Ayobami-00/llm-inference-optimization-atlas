# V1 Schemas

JSON Schema Draft 2020-12 is the canonical Atlas contract language. YAML files
are validated as their JSON data model.

Canonical IDs use:

```text
https://ayobami-00.github.io/llm-inference-optimization-atlas/schemas/v1/<group>/<name>.schema.json
```

Every artifact composes `common/artifact.schema.json`, declares its exact
`kind`, and rejects unevaluated properties. Extensibility is explicit through
namespaced keys in `extensions`.

V1 may change until the first `v1.0.0` release. After release, breaking contract
changes require a new schema version.
