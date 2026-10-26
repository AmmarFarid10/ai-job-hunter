/** Classify links without fetching a page or assuming a post identifies one vacancy. */
export function describeSource(value) {
  if (typeof value !== "string") return null;
  let url;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (
    !["https:", "http:"].includes(url.protocol) ||
    url.username ||
    url.password
  )
    return null;
  const host = url.hostname.toLowerCase();
  const linkedin = host === "linkedin.com" || host.endsWith(".linkedin.com");
  if (linkedin && /^\/jobs\/view\/(?:[^/]*-)?\d+\/?$/.test(url.pathname))
    return {
      url: url.href,
      type: "linkedin_job",
      label: "LinkedIn job listing",
      action: "Review LinkedIn job listing",
    };
  if (
    linkedin &&
    (url.pathname.startsWith("/posts/") ||
      url.pathname.startsWith("/feed/update/"))
  )
    return {
      url: url.href,
      type: "linkedin_post",
      label: "LinkedIn hiring post",
      action: "Review LinkedIn hiring post",
    };
  if (linkedin)
    return {
      url: url.href,
      type: "linkedin_page",
      label: "LinkedIn page",
      action: "Review LinkedIn page",
    };
  return {
    url: url.href,
    type: "company_careers",
    label: "Company / careers page",
    action: "Review company / careers page",
  };
}
