# Machine learning is deferred past v1

Machine learning is one of the project's three learning goals (alongside containers and databases), but it is deliberately out of scope for v1, which ships as a plain prompt-and-answer diary with no model anywhere in it.

Two reasons, neither of which is "we ran out of time". First, the interesting ML here needs data that does not exist yet: semantic search or theme-clustering over the diary only becomes meaningful after months of real answers. Second, the deployment target is a Raspberry Pi 4 with 2GB of RAM, which cannot host a language model of useful size — so the honest options at v1 would have been an API call to a hosted model, which is API plumbing rather than machine learning, or nothing.

## Consequences

When ML does arrive, the natural first form is offline analysis run on a laptop against a database dump, not inference on the Pi. That sidesteps the memory ceiling entirely and is a better learning exercise than prompt-plumbing.

Answers are stored as raw text with timestamps and authorship, which is all that later analysis needs; no ML-specific columns are being added speculatively.

The answers will be in German (see the language decision), which narrows model choice later: multilingual embedding models are fine, several convenient English-only models are not.
