"""joseph -> a deterministic (non-ai) osint query synthesis and evidence correlation engine.

joseph converts a structured investigation objective into a family of search queries,
scores and prioritizes them, optionally executes them through permitted public search
interfaces, normalizes and deduplicates results, scores relevance, extracts and resolves
entities, builds a provenance-backed evidence graph, and renders an intelligence report.

there is no llm anywhere in this pipeline. every stage is a classical algorithm:
regex, finite grammars, string metrics (levenshtein / jaro-winkler), tf-idf, and
deterministic scoring. the same input always produces the same output.

boundary: joseph operates only on publicly accessible information and documented search
operators. it does not bypass authentication, access private accounts, or obtain
restricted records.
"""

__version__ = "1.0.0"
__agency__ = "ASHERIN INTELLIGENCE AGENCY"
