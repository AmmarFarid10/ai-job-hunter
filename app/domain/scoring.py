import calendar
import json
import math
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.matching import (
    CandidateFacts,
    Decision,
    JobFacts,
    MatchResult,
    Requirements,
    known_skills,
)


def verified_skills(names: list[str]) -> set[str]:
    result: set[str] = set()
    for name in names:
        result.update(known_skills(name))
        result.add(name.casefold().strip())
    return result


def industry_years(
    experiences: list[dict[str, Any]], as_of: date, *, lower_bound: bool = True
) -> tuple[float, list[str]]:
    intervals: list[tuple[date, date]] = []
    warnings = []
    for row in experiences:
        if not row.get("verified"):
            continue
        title = str(row.get("title", ""))
        if not re.search(r"engineer|developer|technical (?:team )?lead", title, re.I):
            continue
        try:
            if row.get("start_date"):
                start = date.fromisoformat(str(row["start_date"]))
            elif row.get("start_month"):
                year, month = map(int, str(row["start_month"]).split("-"))
                # Latest possible start and earliest possible end give a conservative lower bound.
                start = date(year, month, calendar.monthrange(year, month)[1] if lower_bound else 1)
            else:
                warnings.append("EXPERIENCE_START_DATE_UNKNOWN")
                continue
            if row.get("end_date"):
                end = date.fromisoformat(str(row["end_date"])) + timedelta(days=1)
            elif row.get("end_month"):
                year, month = map(int, str(row["end_month"]).split("-"))
                end = date(
                    year, month, 1 if lower_bound else calendar.monthrange(year, month)[1]
                ) + timedelta(days=1)
            elif row.get("is_current") is True:
                end = as_of + timedelta(days=1)
            else:
                warnings.append("EXPERIENCE_END_DATE_UNKNOWN")
                continue
            end = min(end, as_of + timedelta(days=1))
            if end > start:
                intervals.append((start, end))
        except (ValueError, TypeError):
            warnings.append("EXPERIENCE_DATE_INVALID")
    merged: list[tuple[date, date]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    days = sum((end - start).days for start, end in merged)
    rounding = math.floor if lower_bound else math.ceil
    return rounding(days / 365.25 * 10000) / 10000, sorted(set(warnings))


def location_eligibility(job: JobFacts, candidate: CandidateFacts) -> tuple[str, list[str]]:
    location = (job.location or "").casefold()
    geography = (job.geographic_restrictions or "").casefold()
    details = location + " " + geography
    candidate_location = (candidate.location or "").casefold()
    in_pakistan = bool(re.search(r"\bpakistan\b", candidate_location))
    # Only explicit exclusion clauses in descriptions can establish a restriction.
    excluded = bool(
        re.search(
            r"(?:not (?:open|available) to|excluding|except|cannot hire in)\s+pakistan",
            job.description,
            re.I,
        )
    )
    if job.pakistan_eligible is False or excluded:
        return "INELIGIBLE", ["PAKISTAN_EXPLICITLY_EXCLUDED"]
    restricted_other = (
        bool(
            re.search(
                r"\b(?:united states|usa|us|u\.s\.|india|canada|united kingdom|uk)\b", details
            )
        )
        and "pakistan" not in details
    )
    candidate_city = candidate_location.split(",", 1)[0].strip()
    city_match = bool(
        candidate_city
        and in_pakistan
        and re.search(r"(?<!\w)" + re.escape(candidate_city) + r"(?!\w)", location)
    )
    if (job.pakistan_eligible is True or city_match) and restricted_other:
        return "UNKNOWN", ["CONFLICTING_GEOGRAPHIC_EVIDENCE"]
    if not candidate_location:
        return "UNKNOWN", ["CANDIDATE_LOCATION_UNKNOWN"]
    if not in_pakistan:
        return "UNKNOWN", ["LOCATION_RULES_REQUIRE_OWNER_REVIEW_OUTSIDE_PAKISTAN"]
    if job.pakistan_eligible is True or city_match or re.search(r"\bpakistan\b", details):
        status, reasons = "ELIGIBLE", ["EXPLICIT_PAKISTAN_LOCATION_OR_ELIGIBILITY"]
    elif restricted_other:
        if "remote" in (details + " " + job.title.casefold()):
            return "INELIGIBLE", ["REMOTE_ROLE_RESTRICTED_TO_ANOTHER_COUNTRY"]
        if candidate.preferences.get("open_to_relocation") is False:
            return "INELIGIBLE", ["RELOCATION_REQUIRED_BUT_DECLINED"]
        return "UNKNOWN", ["RELOCATION_AND_WORK_AUTHORIZATION_NEED_CONFIRMATION"]
    else:
        return "UNKNOWN", ["PAKISTAN_ELIGIBILITY_UNCONFIRMED"]
    authorization = (job.work_authorization or "").casefold()
    explicit_auth = re.search(
        r"(?:must|require[sd]?).{0,45}(?:authorized|authorised|authorization|right to work)",
        job.description,
        re.I,
    )
    if authorization or explicit_auth:
        countries = candidate.preferences.get("work_authorized_countries") or []
        if not isinstance(countries, list) or not any(
            re.search(
                r"(?<!\w)" + re.escape(str(country).casefold()) + r"(?!\w)",
                (authorization or (explicit_auth.group(0).casefold() if explicit_auth else "")),
            )
            for country in countries
        ):
            return "UNKNOWN", ["REQUIRED_WORK_AUTHORIZATION_UNVERIFIED"]
    return status, reasons


def salary_fit(job: JobFacts, preferences: dict[str, object]) -> tuple[str, list[str]]:
    minimum = preferences.get("minimum_annual_salary")
    if minimum is None:
        return "NOT_CONFIGURED", []
    currency = str(preferences.get("salary_currency") or "").upper()
    text = job.compensation or ""
    low: Decimal | None = None
    high: Decimal | None = None
    actual_currency = ""
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("value"), dict):
            value = data["value"]
            if str(value.get("unitText", "")).upper() in {"YEAR", "ANNUAL"}:
                actual_currency = str(data.get("currency", "")).upper()
                if value.get("minValue") is not None:
                    low = Decimal(str(value["minValue"]))
                if value.get("maxValue") is not None:
                    high = Decimal(str(value["maxValue"]))
        elif isinstance(data, dict) and str(data.get("interval", "")).lower() in {"year", "annual"}:
            actual_currency = str(data.get("currency", "")).upper()
            low = Decimal(str(data["min"])) if data.get("min") is not None else None
            high = Decimal(str(data["max"])) if data.get("max") is not None else None
    except (ValueError, TypeError, InvalidOperation):
        pass
    match = re.search(
        r"\b(USD|PKR|EUR|GBP|CAD)\s*([\d,]+)\s*(?:-|–|to)\s*([\d,]+)"
        r"\s*(?:/\s*(?:year|yr)|per year|annually|annual)\b",
        text,
        re.I,
    )
    if match:
        actual_currency = match[1].upper()
        low, high = Decimal(match[2].replace(",", "")), Decimal(match[3].replace(",", ""))
    if not currency or actual_currency != currency or low is None or high is None:
        return "UNKNOWN", ["ANNUAL_COMPENSATION_NOT_COMPARABLE"]
    if not low.is_finite() or not high.is_finite() or low < 0 or low > high:
        return "UNKNOWN", ["COMPENSATION_RANGE_INVALID"]
    requested = Decimal(str(minimum))
    if high < requested:
        return "BELOW_MINIMUM", ["SALARY_BELOW_USER_MINIMUM"]
    if low < requested:
        return "UNKNOWN", ["SALARY_RANGE_OVERLAPS_USER_MINIMUM"]
    return "ACCEPTABLE", []


def score_match(
    candidate: CandidateFacts,
    job: JobFacts,
    requirements: Requirements,
    threshold: int,
    as_of: date,
) -> MatchResult:
    verified = verified_skills(candidate.verified_skills) if candidate.verified else set()
    unverified = verified_skills(candidate.unverified_skills) - verified
    matched, missing_required, missing_preferred, unverified_required = [], [], [], []
    weight_total = weight_matched = 0
    for row in requirements.skills:
        weight = 3 if row.importance == "required" else 1
        weight_total += weight
        accepted = {row.skill.casefold(), *(item.casefold() for item in row.alternatives)}
        if verified & accepted:
            matched.append(row.skill)
            weight_matched += weight
        else:
            if row.importance == "required":
                missing_required.append(row.skill)
            elif row.importance == "preferred":
                missing_preferred.append(row.skill)
            if unverified & accepted:
                unverified_required.append(row.skill)
    skills_points = int(60 * weight_matched / weight_total) if weight_total else 0
    years, reasons = industry_years(candidate.experiences, as_of)
    upper_years, _ = industry_years(candidate.experiences, as_of, lower_bound=False)
    minimum = requirements.minimum_years
    precision_uncertain = minimum is not None and years < minimum <= upper_years
    enough_years = minimum is None or years >= minimum
    experience_points = (
        20 if minimum is None else min(20, int(20 * years / minimum)) if minimum else 20
    )
    specific_years = minimum is not None and requirements.experience_scope != "general"
    if specific_years:
        experience_points = 0
        reasons.append("SPECIFIC_EXPERIENCE_YEARS_UNVERIFIED")
    if precision_uncertain:
        reasons.append("MONTH_PRECISION_COULD_AFFECT_EXPERIENCE_THRESHOLD")
    elif not enough_years:
        reasons.append("INDUSTRY_EXPERIENCE_BELOW_REQUIREMENT")
    # Role family uses explicit verified titles, never the summary's self-reported seniority.
    titles = " ".join(
        str(row.get("title", "")) for row in candidate.experiences if row.get("verified")
    )

    def seniority(value: str) -> int:
        for level, pattern in [
            (6, r"director|head of"),
            (5, r"principal"),
            (4, r"staff"),
            (3, r"lead|manager"),
            (2, r"senior"),
        ]:
            if re.search(pattern, value, re.I):
                return level
        return 1

    senior_role = seniority(titles)
    job_senior = seniority(job.title)
    roles = candidate.preferences.get("roles") or []
    target = bool(
        re.search(
            r"python|backend|fastapi|\bai\b|llm|agentic|technical lead|engineering lead",
            job.title,
            re.I,
        )
    )
    if isinstance(roles, list) and roles:
        requested = " ".join(str(role) for role in roles)
        families = [r"python", r"backend", r"fastapi", r"\bai\b", r"llm", r"agentic", r"lead"]
        target = any(
            re.search(term, requested, re.I) and re.search(term, job.title, re.I)
            for term in families
        ) or any(str(role).casefold() in job.title.casefold() for role in roles)
    role_points = 10 if target and senior_role >= job_senior else 0
    if not target:
        reasons.append("ROLE_FAMILY_OUTSIDE_PREFERENCES")
    if senior_role < job_senior:
        reasons.append("SENIORITY_NOT_DEMONSTRATED_BY_VERIFIED_TITLES")
    eligibility, eligibility_reasons = location_eligibility(job, candidate)
    reasons.extend(eligibility_reasons)
    salary, salary_reasons = salary_fit(job, candidate.preferences)
    reasons.extend(salary_reasons)
    components = {
        "skills": skills_points,
        "experience": experience_points,
        "role_and_seniority": role_points,
        "location": 10 if eligibility == "ELIGIBLE" else 0,
    }
    score = sum(components.values())
    if not requirements.skills:
        reasons.append("REQUIREMENT_EXTRACTION_INCOMPLETE")
    if not candidate.verified:
        reasons.append("PROFILE_NOT_VERIFIED")
    if missing_required:
        reasons.append("MISSING_OR_UNVERIFIED_REQUIRED_SKILLS")
    if unverified_required:
        reasons.append("UNVERIFIED_SKILLS_NOT_CREDITED")
    decision: Decision
    if eligibility == "INELIGIBLE" or salary == "BELOW_MINIMUM":
        decision = "INELIGIBLE"
    elif (
        not candidate.verified
        or eligibility == "UNKNOWN"
        or salary == "UNKNOWN"
        or specific_years
        or precision_uncertain
        or not requirements.skills
        or not job.description.strip()
        or unverified_required
        or reasons.count("EXPERIENCE_START_DATE_UNKNOWN")
        or reasons.count("EXPERIENCE_END_DATE_UNKNOWN")
        or "AMBIGUOUS_SKILL_ALTERNATIVES" in requirements.warnings
    ):
        decision = "REVIEW_REQUIRED"
    elif score < threshold:
        decision = "BELOW_THRESHOLD"
    elif missing_required or not enough_years or not role_points:
        decision = "NOT_QUALIFIED"
    else:
        decision = "QUALIFIED"
    reasons.extend(requirements.warnings)
    return MatchResult(
        score=score,
        threshold=threshold,
        decision=decision,
        matched_skills=sorted(matched),
        missing_required_skills=sorted(missing_required),
        missing_preferred_skills=sorted(missing_preferred),
        unverified_skills=sorted(unverified_required),
        components=components,
        reasons=sorted(set(reasons)),
        industry_years_lower_bound=years,
        industry_years_upper_bound=upper_years,
        eligibility=eligibility,
        salary=salary,
        remote_priority=int(
            eligibility == "ELIGIBLE"
            and "remote" in (job.location or "").casefold()
            and candidate.preferences.get("remote_pakistan_priority", True) is True
        ),
        as_of=as_of,
    )
