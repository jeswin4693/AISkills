"""The guide: a diagram of how a project works, read from its README and docs (slice AB, docs/how-it-works.md).

Kept light on purpose: `builder.github` imports `guide.docs` to decide which doc files a downloaded copy keeps, so nothing heavy
(the model call, the graph) is imported here.
"""
