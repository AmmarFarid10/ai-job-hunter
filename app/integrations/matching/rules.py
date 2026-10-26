import re
from typing import Protocol

from app.domain.matching import (
    ExperienceScope,
    Importance,
    Requirements,
    SkillRequirement,
    contains_skill,
    known_skills,
)
from app.integrations.discovery.base import ProviderError
from app.integrations.discovery.parsing import plain_text


class RequirementExtractor(Protocol):
    async def extract(self, title: str, description: str) -> Requirements: ...


PREFERRED = re.compile(r"preferred|nice.to.have|bonus|desirable|a plus|ideally", re.I)
REQUIRED = re.compile(
    r"required|must|minimum|essential|proficien|expertise|experience (?:with|in)|strong", re.I
)
HEADINGS = re.compile(r"^(?:[\w /&-]{1,65}:?|what .{1,60})$", re.I)
YEAR_PATTERN = re.compile(
    r"(?P<years>\d{1,2}(?:\.\d)?)\s*(?:\+|[-–]\s*\d{1,2})?\s*years?\s+"
    r"(?:of\s+)?(?P<context>[^\n.;]{0,140}experience[^\n.;]{0,100})",
    re.I,
)


def importance(evidence: str, context: str = "") -> Importance:
    if PREFERRED.search(evidence) or PREFERRED.search(context):
        return "preferred"
    if REQUIRED.search(evidence) or REQUIRED.search(context):
        return "required"
    return "mentioned"


def extract_rules(title: str, description: str) -> Requirements:
    text = plain_text(description)
    found: dict[str, SkillRequirement] = {}
    warnings: list[str] = []
    title_keys = known_skills(title)
    title_alternatives = len(title_keys) > 1 and bool(re.search(r"\bor\b|/", title, re.I))
    if title_alternatives:
        warnings.append("AMBIGUOUS_SKILL_ALTERNATIVES")
    for skill in sorted(title_keys):
        found[skill] = SkillRequirement(
            skill=skill,
            importance="mentioned" if title_alternatives else "required",
            evidence=title,
        )
    context = ""
    ranking = {"mentioned": 0, "preferred": 1, "required": 2}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if HEADINGS.fullmatch(line) and len(line.split()) < 10:
            # Reset at section boundaries; preferred headings must not leak into requirements.
            if re.search(
                r"qualifications|requirements|what you.bring|what we.look|preferred|bonus|"
                r"responsibilities|benefits|about|what you.ll.do",
                line,
                re.I,
            ):
                context = line
        for sentence in re.split(r"(?<=[.;])\s+", line):
            keys = known_skills(sentence)
            # Ambiguous alternative clauses require review rather than inferred mandatory skills.
            alternatives = bool(re.search(r"\bor\b|and/or", sentence, re.I)) and len(keys) > 1
            for skill in sorted(keys):
                level = importance(sentence, context)
                evidence = sentence[:1500]
                if level == "required" and context and not REQUIRED.search(evidence):
                    # Evidence stays an exact source substring; classification context is auditable.
                    level = "mentioned"
                if alternatives and level == "required":
                    level = "mentioned"
                    warnings.append("AMBIGUOUS_SKILL_ALTERNATIVES")
                candidate = SkillRequirement(
                    skill=skill, importance=level, evidence=evidence, alternatives=[]
                )
                previous = found.get(skill)
                if previous is None or ranking[candidate.importance] > ranking[previous.importance]:
                    found[skill] = candidate
    years = list(YEAR_PATTERN.finditer(text))
    chosen = max(years, key=lambda match: float(match.group("years")), default=None)
    evidence = chosen.group(0) if chosen else None
    scope: ExperienceScope = "unknown"
    if evidence:
        scope = "specific" if known_skills(evidence) else "general"
    if not found:
        warnings.append("NO_RECOGNIZED_SKILL_REQUIREMENTS")
    if chosen and scope == "specific":
        warnings.append("SKILL_SPECIFIC_EXPERIENCE_DURATION_NEEDS_REVIEW")
    return Requirements(
        skills=list(found.values()),
        minimum_years=float(chosen.group("years")) if chosen else None,
        experience_evidence=evidence,
        experience_scope=scope,
        warnings=sorted(set(warnings)),
    )


def validate_evidence(requirements: Requirements, title: str, description: str) -> None:
    text = plain_text(description)
    source = " ".join((title + "\n" + text).split()).casefold()
    for row in requirements.skills:
        evidence = " ".join(row.evidence.split()).casefold()
        if evidence not in source or not contains_skill(row.evidence, row.skill):
            raise ProviderError("UNSUPPORTED_REQUIREMENT_EVIDENCE")
        if any(not contains_skill(row.evidence, item) for item in row.alternatives):
            raise ProviderError("UNSUPPORTED_ALTERNATIVE_EVIDENCE")
        if row.alternatives and not re.search(r"\bor\b|and/or", row.evidence, re.I):
            raise ProviderError("UNSUPPORTED_ALTERNATIVE_EVIDENCE")
    if requirements.minimum_years is not None:
        evidence = requirements.experience_evidence or ""
        if not evidence or " ".join(evidence.split()).casefold() not in source:
            raise ProviderError("UNSUPPORTED_EXPERIENCE_EVIDENCE")
        years = [float(match.group("years")) for match in YEAR_PATTERN.finditer(evidence)]
        if requirements.minimum_years not in years:
            raise ProviderError("UNSUPPORTED_EXPERIENCE_EVIDENCE")


class RulesExtractor:
    async def extract(self, title: str, description: str) -> Requirements:
        return extract_rules(title, description)
