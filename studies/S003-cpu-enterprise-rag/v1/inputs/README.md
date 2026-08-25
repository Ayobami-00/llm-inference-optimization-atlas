# Enterprise RAG fixture

`documents.jsonl` contains 24 short, repository-owned fictional enterprise documents spanning
security, operations, support, finance, people operations, and data governance.
`questions.jsonl` contains twelve grounded questions with frozen relevant-document IDs and
deterministic answer keywords.

No organization, customer, employee, credential, or real policy is represented. The corpus is
small by design: it exercises the complete retrieval and generation process on consumer CPUs but
does not establish transferability to production enterprise collections. All records are licensed
under Apache-2.0.
