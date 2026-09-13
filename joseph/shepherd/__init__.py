"""shepherd -> a symbolic pattern execution engine (not an ai brain).

the reference "data brains" are compiled into machine data (ontology, relations, flaw
types, pattern schema, taxonomy) plus executable pattern objects. a normal deterministic
software runtime consumes them:

    ontology   -> domains / concepts / relations / flaws / schema
    patterns   -> universal pattern objects (trigger, preconditions, operations, tests)
    rules      -> routing / scoring / validation / contradiction / adaptation
    runtime    -> registry, knowledge graph, router, pattern engine, creator, audit

shepherd sits below the intelligence engine and above the individual algorithms: it
decides which pattern applies and what operation comes next. it never generates prose and
never claims autonomous model self-modification -> pattern learning happens through these
files and the registry only.
"""

from pathlib import Path

SHEPHERD_ROOT = Path(__file__).resolve().parent
ONTOLOGY_DIR = SHEPHERD_ROOT / "ontology"
PATTERNS_DIR = SHEPHERD_ROOT / "patterns"
RULES_DIR = SHEPHERD_ROOT / "rules"
