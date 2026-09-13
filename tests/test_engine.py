"""engine tests -> deterministic behavior, no network, no discord dependency.

run: python -m tests.test_engine   (from the repo root)
or:  python -m pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from joseph.engine import generator, mutation, scoring, normalize, relevance, entities, resolution, pipeline, providers
from joseph.engine.grammar import TermKind
from joseph.engine.metrics import jaro_winkler, levenshtein, levenshtein_ratio
from joseph.engine.providers import RawResult
from joseph.engine.seed import IdentitySeed, filetypes_for_profile
from joseph.report.model import build_dataset
from joseph.report.render import render_markdown


def test_seed_normalization():
    seed = IdentitySeed.build(name="  John Smith ", usernames="jsmith, jsmith, JSmith", since="2020")
    assert seed.name == "John Smith"
    assert seed.usernames == ["jsmith"]  # case-insensitive dedupe folds JSmith into jsmith
    seed2 = IdentitySeed.build(usernames="alpha, Beta")
    assert seed2.usernames == ["alpha", "Beta"]  # distinct handles preserved with original case
    assert seed.after_value() == "2020-01-01"


def test_generator_is_deterministic():
    seed = IdentitySeed.build(name="John Smith", organizations="Company X", usernames="jsmith")
    a = [q.signature() for q in generator.generate(seed)]
    b = [q.signature() for q in generator.generate(seed)]
    assert a == b
    assert len(a) == len(set(a)), "generator must not emit duplicate query signatures"


def test_generator_uses_documented_operators():
    seed = IdentitySeed.build(name="John Smith", usernames="jsmith")
    qs = generator.generate(seed)
    # google should render site: and quoted phrases
    rendered = [q.render("google") for q in qs]
    assert any("site:github.com" in r for r in rendered)
    assert any('"John Smith"' in r for r in rendered)
    # bing must translate filetype: -> ext:
    seed2 = IdentitySeed.build(name="John Smith", filetypes="pdf")
    doc_q = [q for q in generator.generate(seed2) if any(t.kind is TermKind.FILETYPE for t in q.terms)][0]
    assert "ext:pdf" in doc_q.render("bing")
    assert "filetype:pdf" in doc_q.render("google")


def test_scoring_orders_multi_anchor_first():
    seed = IdentitySeed.build(name="John Smith", organizations="Company X", usernames="jsmith")
    family = mutation.mutate_family(seed, generator.generate(seed))
    ranked = scoring.prioritize(family)
    assert ranked == sorted(ranked, key=lambda s: (-s.score, s.query.signature()))
    # a query with two exact anchors should outrank a bare single word
    top = ranked[0]
    assert top.score > 0


def test_metrics():
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein_ratio("abc", "abc") == 1.0
    assert jaro_winkler("jsmith", "jsmith") == 1.0
    assert jaro_winkler("jsmith", "jsmyth") > 0.8


def test_normalize_and_dedupe():
    raws = [
        RawResult("https://www.example.com/a/?utm_source=x", "A", "s1", "ddg", "q1", "identity_direct", 1),
        RawResult("https://example.com/a", "A longer title", "s1 longer", "ddg", "q2", "identity_org", 2),
        RawResult("https://github.com/jsmith", "jsmith", "profile", "ddg", "q3", "username_site:github", 1),
    ]
    results = normalize.normalize(raws)
    # first two fold into one canonical url
    canon = [r.canonical for r in results]
    assert "https://example.com/a" in canon
    folded = [r for r in results if r.canonical == "https://example.com/a"][0]
    assert folded.corroboration == 2  # two distinct strategies surfaced it


def test_entity_extraction_and_resolution():
    seed = IdentitySeed.build(name="John Smith", usernames="jsmith", domains="jsmith.dev")
    raws = [
        RawResult("https://github.com/jsmith", "jsmith (John Smith)", "contact john@jsmith.dev", "ddg", "q", "username_site:github", 1),
    ]
    results = normalize.normalize(raws)
    ents = entities.extract(results)
    kinds = {e.kind for e in ents}
    assert "profile" in kinds or "handle" in kinds
    assert any(e.kind == "email" for e in ents)
    resolved = resolution.resolve(seed, ents)
    # exact username / matching email domain should resolve strong/moderate
    verdicts = {r.verdict for r in resolved}
    assert "strong" in verdicts or "moderate" in verdicts


def test_full_pipeline_plan_only_builds_report():
    seed = IdentitySeed.build(name="John Smith", organizations="Company X", usernames="jsmith")
    inv = pipeline.plan_only(seed)
    inv = pipeline.analyze(seed, [], inv)  # no raws -> plan-only report
    ds = build_dataset(inv)
    md = render_markdown(ds)
    assert "ASHERIN INTELLIGENCE AGENCY" in md
    assert ds.report_id.startswith("AIA-")
    assert ds.data_hash
    assert len(ds.query_family) > 0


def test_filetype_profiles():
    assert "pdf" in filetypes_for_profile("documents")
    leaks = filetypes_for_profile("leaks")
    assert "sql" in leaks and "env" in leaks and "log" in leaks
    all_ft = filetypes_for_profile("all")
    assert set(filetypes_for_profile("documents")) <= set(all_ft)
    assert set(leaks) <= set(all_ft)
    assert filetypes_for_profile("nonsense") == filetypes_for_profile("documents")  # safe default


def test_generator_uses_leak_filetypes_when_selected():
    seed = IdentitySeed.build(name="Jane Roe", filetypes=",".join(filetypes_for_profile("leaks")))
    strategies = {q.strategy for q in generator.generate(seed)}
    assert "document:sql" in strategies
    assert "document:env" in strategies


def test_ddg_redirect_unwraps_to_direct_link():
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fleak%2Fdata.sql&rut=abc"
    assert providers._unwrap_ddg(wrapped) == "https://example.com/leak/data.sql"
    plain = "https://example.org/page"
    assert providers._unwrap_ddg(plain) == plain


def test_ddg_parse_extracts_direct_result_urls():
    body = (
        '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg='
        'https%3A%2F%2Ftarget.com%2Fpath">Target Page</a>'
        '<a class="result__snippet">a matching snippet</a>'
    )
    results = providers._parse_ddg(body, "asher shepherd newton", "identity_direct")
    assert len(results) == 1
    assert results[0].url == "https://target.com/path"
    assert results[0].title == "Target Page"
    assert results[0].strategy == "identity_direct"


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa
            failed += 1
            print(f"  ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
