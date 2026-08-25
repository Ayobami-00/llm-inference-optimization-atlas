# Registry

The registry contains immutable, reusable objects selected by studies. A registry record identifies
one exact dataset revision, evaluator implementation, model representation, hardware topology, or
runtime build. It does not contain experimental outcomes.

Every record:

- validates against a frozen V1 schema;
- cites official metadata through the external source registry;
- pins mutable upstreams by commit, digest, or repository-owned file hash;
- excludes credentials, machine serials, UUIDs, hostnames, usernames, and network identifiers; and
- receives a new identity or version when a change would affect reproducibility.

Study configurations reference these records with `atlas://` URIs. Runtime knobs that vary within an
experiment belong in study configuration objects rather than in a shared runtime-build record.
