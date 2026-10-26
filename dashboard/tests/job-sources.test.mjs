import test from "node:test";
import assert from "node:assert/strict";
import { describeSource } from "../lib/job-sources.mjs";
test("source types distinguish one vacancy from posts and general pages", () => {
  for (const url of [
    "https://www.linkedin.com/jobs/view/12345",
    "https://pk.linkedin.com/jobs/view/backend-engineer-12345?trk=feed",
  ])
    assert.equal(describeSource(url)?.type, "linkedin_job");
  for (const url of [
    "https://www.linkedin.com/posts/recruiter-hiring-123",
    "https://linkedin.com/feed/update/urn:li:activity:123",
  ])
    assert.equal(describeSource(url)?.type, "linkedin_post");
  assert.equal(
    describeSource("https://linkedin.com/company/example/jobs")?.type,
    "linkedin_page",
  );
  assert.equal(
    describeSource("https://boards.greenhouse.io/example/jobs/123")?.type,
    "company_careers",
  );
  assert.equal(
    describeSource("https://linkedin.com.evil.example/jobs/view/123")?.type,
    "company_careers",
  );
});
test("review links reject unsafe schemes and embedded credentials", () => {
  for (const url of [
    null,
    undefined,
    "not a URL",
    "javascript:alert(1)",
    "data:text/html,x",
    "//example.com",
    "https://user:password@example.com/jobs/1",
  ])
    assert.equal(describeSource(url), null);
  const source = describeSource("https://example.com/careers/123?ref=search");
  assert.equal(source.url, "https://example.com/careers/123?ref=search");
});
