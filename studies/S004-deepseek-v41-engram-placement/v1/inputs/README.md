# Frozen S004 inputs

`trace-spec.yaml` is the machine-readable source of truth for every generated
request. The execution bundle expands it only after loading the pinned
DeepSeek-V4.1 encoding implementation, then verifies every rendered prompt has
the requested token count. Generated traces are written to `.atlas/work`; they
are never edited by hand or committed as evidence.

`correctness-cases.jsonl` contains two semantic seeds for each content family.
The generator expands every seed to 1K, 8K, 32K, and 128K input lengths and to
batch shapes 1 and 8. The same token IDs are replayed in all three conditions.

The primary matrix uses unique prefixes. The repeated-prefix probe is separately
labelled and cannot influence the confirmatory SLO-capacity result. Atlas
publishes both as exact scopes with `prefix_mode=unique` or
`prefix_mode=shared-50-percent`, so the exploratory probe cannot be mistaken for
or aggregated into the corresponding primary 32K-by-8 cell.

`model-manifest.yaml` freezes 57 files totaling 510,310,624,019 bytes. Its
canonical aggregate SHA-256 is
`c5a37ff491e09e9abd947d0823e428679e4e3bd94944adfe7ab16f7b91691eeb`.
