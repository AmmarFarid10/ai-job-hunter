import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.schemas import Education, Experience
from tests.test_api import candidate


@pytest.mark.parametrize(
    "values",
    [
        {"start_month": "2024-13"},
        {"start_month": "2024-00"},
        {"start_month": "2024-6"},
        {"start_month": "2024-06", "end_month": "2024-05"},
        {"start_date": "2024-06-12", "start_month": "2024-06"},
        {"end_date": "2024-06-12", "end_month": "2024-06"},
        {"start_month": "2024-06", "end_date": "2024-05-31"},
        {"is_current": True, "end_month": "2024-06"},
    ],
)
def test_invalid_employment_boundaries(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Experience.model_validate({"employer": "Example", "title": "Engineer", **values})


def test_education_year_order() -> None:
    with pytest.raises(ValidationError):
        Education(institution="Example", degree="BS", start_year=2020, graduation_year=2018)


async def test_month_profile_confirmation_preserves_precision(client: AsyncClient) -> None:
    cid = await candidate(client)
    response = await client.put(
        f"/api/v1/candidates/{cid}/profile",
        json={
            "name": "Confirmed Example",
            "confirmed": True,
            "skills": ["Python"],
            "experiences": [
                {
                    "employer": "Current Employer",
                    "title": "Engineer",
                    "start_month": "2024-06",
                    "is_current": True,
                },
                {
                    "employer": "Past Employer",
                    "title": "Engineer",
                    "start_month": "2021-09",
                    "end_month": "2024-05",
                    "is_current": False,
                },
            ],
            "education": [
                {
                    "institution": "Example",
                    "degree": "MS",
                    "start_year": 2018,
                    "graduation_year": 2020,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    stored = (await client.get(f"/api/v1/candidates/{cid}")).json()
    assert stored["verified"] is True
    assert stored["education"][0]["start_year"] == 2018
    assert stored["review_warnings"] == []
    current = next(row for row in stored["experiences"] if row["is_current"])
    assert current["start_month"] == "2024-06"
    assert current["start_date"] is None and current["end_date"] is None
    assert current["end_month"] is None and current["verified"] is True
