# Native Transformers CPU bundle

This bundle runs real SmolLM2-135M-Instruct inference through pinned Transformers and PyTorch versions.
Preparation displays the Apache-2.0 model license and 272 MB download before writing immutable files to
the shared `.atlas/cache`. Running is offline and creates draft evidence only; review and promote each run
explicitly with `atlas evidence validate` and `atlas evidence promote`.

The quick profile exercises every experiment with one replicate and three requests. The full profile uses
all twelve conversations and the preregistered seeds 101, 202, and 303. No model weights are committed.
