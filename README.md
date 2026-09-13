# joseph

a deterministic, non-ai osint query synthesis and evidence correlation engine, delivered
as a discord bot and deployed on railway.

joseph converts what you know about a subject into a ranked family of search queries,
optionally executes them through permitted public search interfaces, normalizes and
deduplicates the results, scores relevance, extracts and resolves entities, builds a
provenance-backed evidence graph, and renders an intelligence report.

there is no llm anywhere in the pipeline. every stage is a classical algorithm: regex,
finite grammars, string metrics (levenshtein / jaro-winkler), tf-idf, and deterministic
scoring. the same input always produces the same output.

## boundary

joseph operates only on publicly accessible information and documented search operators.
it does not bypass authentication, access private accounts, or obtain restricted records.
absence from search results is never treated as proof of absence.

the vision layer is deliberately **not** an unrestricted biometric surveillance tool. face
matching, scene/landmark geolocation, and perceptual hashing are pluggable evidence
channels that stay disabled unless an explicitly authorized model backend and a corpus you
are permitted to search are wired in — joseph ships neither, and those channels report
`CANNOT_RESOLVE`. visual similarity is evidence for a candidate, never proof of identity;
face recognition, environment recognition, and geographic evidence are kept as separate
streams and only correlated by the evidence engine.

## architecture

shepherd (symbolic control plane) sits *below* the intelligence engine and *above* the
individual algorithms. it is compiled from the reference "data brains" into machine data,
not run as an ai:

```
shepherd/
  ontology/        domains.json (pattern-forge routing domains) · relations.json
                   (relation algebra) · flaw_types.json (26 audit classes) ·
                   pattern_schema.json (universal pattern object) · taxonomy.json (28/274)
  patterns/osint/  executable universal pattern objects (identity.confirmation, ...)
  rules/           routing · scoring · validation · contradiction · adaptation
  registry.py      loads + validates + versions patterns (status lifecycle)
  knowledge_graph.py  typed pattern graph (executes known relations, no inference)
  router.py        deterministic task classification -> domains + patterns
  pattern_engine.py   selects applicable patterns -> maps operations to query strategies
  creator.py       pattern creator = a compiler (mine -> classify -> score -> test ->
                   propose candidate; compose / adapt / retire; never overwrites a version)
  audit.py         model audit over the assessment (flaw taxonomy + contradiction rules)
```

vision / geo evidence layer -> visual similarity is a *lead*, not proof of identity:

```
joseph/vision/
  exif.py          dependency-free exif + gps reader (real, deterministic location evidence)
  provenance.py    content hash / size / format sniff (chain of custody)
  channels.py      independent evidence channels; face/scene/phash are DISABLED by
                   design -> CANNOT_RESOLVE unless an authorized backend + corpus is wired
  engine.py        evidence engine: keeps streams separate, preserves the epistemic firewall
```

the pipeline itself:

```
identity seed
    -> shepherd route         (task type, domains, patterns applied)
    -> query grammar         (typed terms; documented operators per provider)
    -> query generator       (query families by strategy)
    -> mutation engine       (synthesis grammar: specialize / generalize / swap_domain)
    -> query scoring          (rank by expected information gain)
    -> providers              (dork urls always; optional live ddg collection)
    -> normalize + dedupe     (canonical url, provenance, corroboration)
    -> relevance              (deterministic tf-idf)
    -> entity extraction      (emails, handles, domains, profiles)
    -> entity resolution      (feature-weighted verdicts; name-only capped at weak)
    -> evidence graph         (typed edges, degree centrality)
    -> findings + confidence  (epistemic firewall, bounded noisy-or)
    -> intelligence report    (json dataset + markdown; ASHERIN INTELLIGENCE AGENCY)
```

module layout mirrors this so the extension points (full graph community detection, a
deterministic pdf renderer, the 25-class model audit, and the downloadable pattern
creator) slot in without a rewrite.

```
joseph/
  bot.py                 discord bot + slash commands
  config.py              env-based config (zero-touch, no secrets logged)
  engine/
    seed.py              identity seed model (hashable, fingerprinted)
    grammar.py           typed terms + per-provider operator serialization
    generator.py         deterministic query families
    mutation.py          pattern-forge synthesis grammar
    scoring.py           query prioritization
    providers.py         dork url builder + optional live ddg adapter
    normalize.py         canonical url + dedupe + provenance
    relevance.py         tf-idf relevance
    metrics.py           levenshtein + jaro-winkler
    entities.py          entity extraction
    resolution.py        entity resolution + graded verdicts
    graph.py             evidence graph + degree centrality
    evidence.py          findings, confidence, contradiction detection
    pipeline.py          orchestrates the stages
  report/
    model.py             intelligence report dataset (provenance + hashes)
    render.py            deterministic markdown renderer
tests/
  test_engine.py         deterministic engine tests (no network, no discord)
```

## slash commands

- `/joseph help` — what joseph is and how to use it.
- `/joseph dork` — generate a ranked query family from what you know. no network calls.
  attaches the full plan (google / bing / ddg strings + urls) as a file.
- `/joseph investigate` — run the full pipeline and return an ASHERIN INTELLIGENCE
  AGENCY report as both markdown and json. live collection is used only when enabled.
  the report now includes a **shepherd routing / patterns applied** section (with pattern
  versions) and a **model audit** section.
- `/joseph route` — show how shepherd classifies a subject: task type, pattern-forge
  domains, and which patterns fire. ephemeral, no network.
- `/joseph vision` — attach an image; returns exif/gps location evidence + content
  provenance as separate evidence channels. biometric face matching is disabled by design
  and reported honestly as `CANNOT_RESOLVE`.
- `/joseph workspace` — create a private research workspace: a category `joseph · <name>`
  with `case-file / queries / findings / sources / media` channels. `private:true`
  (default) makes it visible only to you and admins. requires the bot to have the
  **Manage Channels** permission.

the investigate/dork/route commands take optional identifiers: `name`, `usernames`,
`emails`, `organizations`, `locations`, `occupations`, `domains`, `sites`, `filetypes`,
`exclusions`, `keywords`, `since`, `until` (dates as `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`).

## local run

```bash
python -m pip install -r requirements.txt
cp .env.example .env        # then set DISCORD_TOKEN
python -m joseph.bot
```

run the tests (no dependencies needed for the engine):

```bash
python tests/test_engine.py
python tests/test_shepherd_vision.py
```

## discord setup

1. create an application at the discord developer portal.
2. under **Bot**, create a bot and copy the token into `DISCORD_TOKEN`.
3. under **Installation** / **OAuth2 -> URL Generator**, select scopes `bot` and
   `applications.commands`. no privileged intents are required. to use
   `/joseph workspace`, also grant the **Manage Channels** bot permission.
4. invite the bot to your server with the generated url.
5. set `GUILD_ID` to your server id for instant slash-command sync during development
   (leave blank for global sync, which can take up to about an hour to appear).

## railway deployment

1. push this repo to github (already wired to `github.com/shep95/joseph`).
2. in railway, create a new project from the github repo.
3. railway detects python via `requirements.txt` and runs the start command in
   `railway.json` / `Procfile`: `python -m joseph.bot`.
4. add service variables: `DISCORD_TOKEN` (required), and optionally `GUILD_ID`,
   `JOSEPH_LIVE_SEARCH`, `JOSEPH_MAX_LIVE_QUERIES`, `JOSEPH_HTTP_TIMEOUT`.
5. deploy. the worker connects to discord and syncs the commands on startup.

## configuration

| variable | default | meaning |
|---|---|---|
| `DISCORD_TOKEN` | (required) | discord bot token |
| `GUILD_ID` | (blank) | single guild id for instant command sync |
| `JOSEPH_LIVE_SEARCH` | `0` | `1` enables best-effort live collection via ddg html |
| `JOSEPH_MAX_LIVE_QUERIES` | `8` | max top queries executed per investigation when live |
| `JOSEPH_HTTP_TIMEOUT` | `12` | per-request http timeout in seconds |

## reproducibility

every report carries a seed fingerprint, a dataset hash, the engine version, and a
report id. the same seed and engine version always produce the same dataset, so a report
can be regenerated and audited.
