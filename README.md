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

## architecture

```
identity seed
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

each command takes optional identifiers: `name`, `usernames`, `emails`,
`organizations`, `locations`, `occupations`, `domains`, `sites`, `filetypes`,
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
```

## discord setup

1. create an application at the discord developer portal.
2. under **Bot**, create a bot and copy the token into `DISCORD_TOKEN`.
3. under **Installation** / **OAuth2 -> URL Generator**, select scopes `bot` and
   `applications.commands`. no privileged intents are required.
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
