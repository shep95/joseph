"""entity resolution.

decides, for each extracted entity, how strongly it relates to the seed identity. never
binary: every candidate gets a feature-weighted score and a graded verdict.

    strong   -> exact username / matching domain / matching email
    moderate -> high name similarity, org/location overlap
    weak     -> partial similarity only
    unknown  -> insufficient signal

a matching name alone is explicitly capped at weak, because name collisions are the
classic false positive.
"""

from __future__ import annotations

from dataclasses import dataclass

from .entities import Entity
from .metrics import jaro_winkler, levenshtein_ratio
from .seed import IdentitySeed

VERDICTS = ("strong", "moderate", "weak", "unknown")


@dataclass(frozen=True)
class ResolvedEntity:
    entity: Entity
    score: float
    verdict: str
    features: tuple[str, ...]


def _best_similarity(value: str, candidates: list[str]) -> float:
    best = 0.0
    for c in candidates:
        s = max(jaro_winkler(value, c), levenshtein_ratio(value, c))
        best = max(best, s)
    return best


def resolve(seed: IdentitySeed, entities: list[Entity]) -> list[ResolvedEntity]:
    seed_usernames = [u.lower() for u in seed.usernames]
    seed_emails = [e.lower() for e in seed.emails]
    seed_domains = [d.lower() for d in seed.domains]

    out: list[ResolvedEntity] = []
    for e in entities:
        features: list[str] = []
        score = 0.0
        val = e.value.lower()

        if e.kind == "email":
            if val in seed_emails:
                score += 1.0
                features.append("exact email match")
            else:
                edomain = val.split("@", 1)[1] if "@" in val else ""
                if edomain and edomain in seed_domains:
                    score += 0.6
                    features.append("email on known domain")
                sim = _best_similarity(val, seed_emails)
                if sim > 0.85:
                    score += 0.4
                    features.append("near-duplicate email")

        elif e.kind in {"handle", "username", "profile"}:
            if val in seed_usernames:
                score += 1.0
                features.append("exact username match")
            else:
                sim = _best_similarity(val, seed_usernames)
                if sim >= 0.92:
                    score += 0.7
                    features.append("high username similarity")
                elif sim >= 0.80:
                    score += 0.35
                    features.append("partial username similarity")
            if e.kind == "profile" and e.surface:
                features.append(f"{e.surface} profile")
                score += 0.1

        elif e.kind == "domain":
            if val in seed_domains:
                score += 1.0
                features.append("exact domain match")
            else:
                # email-domain overlap
                for em in seed_emails:
                    if "@" in em and em.split("@", 1)[1] == val:
                        score += 0.6
                        features.append("matches email domain")
                        break

        verdict = _verdict(score, e)
        out.append(ResolvedEntity(entity=e, score=round(score, 4), verdict=verdict, features=tuple(features)))

    out.sort(key=lambda r: (-r.score, r.entity.kind, r.entity.value.lower()))
    return out


def _verdict(score: float, entity: Entity) -> str:
    if score >= 0.9:
        return "strong"
    if score >= 0.5:
        return "moderate"
    if score > 0.0:
        return "weak"
    return "unknown"
