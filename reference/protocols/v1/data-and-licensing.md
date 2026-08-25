# V1 data and licensing protocol

## Data inventory

Every dataset, trace, prompt collection, model, tokenizer, runtime, container, and generated artifact
must have an owner, origin, license or terms, version, retrieval date, and redistribution decision.
Registry metadata records facts; the study records the exact selected revision and fingerprint.

## Classification

Classify inputs as one of:

- repository-owned and redistributable;
- public third-party and redistributable under stated terms;
- public third-party but download-only;
- private or restricted and represented only by non-sensitive summaries;
- synthetic, with generation method and seed.

V1 committed studies use repository-owned or clearly redistributable compact inputs. Private data,
credentials, access tokens, user identifiers, and machine identifiers are prohibited in committed
evidence.

## Dataset terms

Record allowed purpose, redistribution, attribution, share-alike obligations, access constraints,
personal-data considerations, and deletion requirements. If terms are ambiguous, do not copy the data
into the repository; add an acquisition step and require the user to acknowledge upstream terms.

## Models and weights

Model records separate code license, weight license, tokenizer terms, and acceptable-use restrictions.
The Atlas never commits model weights. Preparation shows model identity, expected size, license, and
source before downloading into `.atlas/cache`.

## Derived data

Transformations include prompts, chunking, redaction, tokenization, quantization calibration,
embeddings, and sampled outputs. Record the producing command or code revision, parameters, seed,
input digests, output digest, and whether the derived object can be redistributed.

Embeddings may retain information about source text and are governed as derived data, not assumed
anonymous. Model responses may reproduce input or training text; review compact committed outputs for
secrets and inappropriate personal data.

## Retention and redaction

Canonical evidence contains only what is necessary to reproduce and assess the claim. Environment
capture uses an allowlist and marks values as captured, redacted, hashed, or omitted. Serial numbers,
UUIDs, MAC addresses, usernames, home paths, cloud account IDs, and access tokens are excluded.

## Review checklist

Reviewers verify that all artifacts resolve, redistribution is permitted, required attribution exists,
generated data is reproducible, checksums match, and no sensitive values appear in logs, paths,
environment snapshots, or outputs. Uncertain licensing blocks evidence acceptance.

Relevant source records include `atlas://source/SRC0080@v1` for GGUF,
`atlas://source/SRC0081@v1` for safetensors, and dataset-specific records in the source registry.
