import json

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.discovery.base import ProviderError
from app.integrations.matching.openai import OpenAIExtractor
from tests.test_discovery_providers import safe_http


async def test_openai_extracts_only_evidenced_skills_without_candidate_data():
    def handler(request):
        assert request.url.host == "api.openai.com" and request.method == "POST"
        body = json.loads(request.content)
        assert body["store"] is False and "tools" not in body
        assert body["text"]["format"]["strict"] is True
        assert "candidate" not in body["input"][0]["content"]
        output = json.dumps(
            {"skills": [{"skill": "Cassandra", "evidence": "Cassandra is required."}]}
        )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": output}]}
                ],
            },
        )

    extractor = OpenAIExtractor(
        safe_http(handler, {"api.openai.com"}), SecretStr("private-test-key"), "configured-model"
    )
    result = await extractor.extract("Python Engineer", "Python and Cassandra is required.")
    assert "cassandra" in {row.skill for row in result.skills}


async def test_openai_fabrication_and_refusal_are_rejected():
    for response in [
        {"status": "incomplete"},
        {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}],
        },
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {"skills": [{"skill": "AWS", "evidence": "Python required."}]}
                            ),
                        }
                    ],
                }
            ],
        },
    ]:
        extractor = OpenAIExtractor(
            safe_http(
                lambda _, payload=response: httpx.Response(200, json=payload), {"api.openai.com"}
            ),
            SecretStr("key"),
            "model",
        )
        with pytest.raises(ProviderError):
            await extractor.extract("Python Engineer", "Python required.")


async def test_openai_is_opt_in_and_requires_configuration():
    with pytest.raises(ProviderError, match="NOT_CONFIGURED"):
        await OpenAIExtractor(safe_http(lambda _: httpx.Response(500)), None, None).extract(
            "Python", "Python required."
        )
