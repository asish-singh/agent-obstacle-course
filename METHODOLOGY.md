# Methodology

This is the public measurement protocol for the Agent Obstacle Course census. It is adapted from SPEC.md sections 2 to 6. The 50 site pilot ran on 15 July 2026 and its review produced one correction, robots.txt evaluation now follows the REP longest match rule with a single authoritative implementation. This protocol is frozen as of 15 July 2026, before the census. Any edit after this point is a deliberate, visible commit.

## What counts as an obstacle

Each site receives a small number of polite page fetches, and the responses are classified against these types. Everything is mechanical, no AI judging, and every classification is traceable to saved evidence in data/raw. Concrete detection rules live in versioned config/signatures.json.

O1, bot wall. The fetch returns a challenge instead of content. Detected by status 403, 429, or 503 combined with known challenge signatures for Cloudflare, Akamai, PerimeterX, DataDome, hCaptcha, and reCAPTCHA. Precedence rule, if O1 fires on all fetch variants, obstacles O2 to O4 are recorded as not assessed, never as zero and never as additional penalties.

O2, JavaScript dependency. The raw HTML contains almost no readable text but a rendered browser sees a full page. Measured as the extracted text ratio of raw to rendered, classified JS dependent when the ratio is under 0.2 and the rendered text exceeds 500 characters. Assessed only when the raw fetch was not bot walled. Both text extracts are saved, truncated to 20 KB, so every ratio is reproducible.

O3, identity discrimination. The site serves substantially different responses to the declared agent user agent than to a stock browser user agent on the plain fetches. Triggered by a different status class, or a text ratio between the two raw fetches under 0.5. This separates "the site needs JavaScript" from "the site treats non browser identities differently."

O4, login wall. The homepage or its redirect target demands authentication. Mechanical rule, HTTP 401, a redirect chain ending at a path matching the versioned login pattern list, or a rendered page whose largest above the fold container includes a password input while total article like text is under 500 characters. A caveat is recorded per site, since for many SaaS domains the homepage legitimately is a login page. These are flagged, not moralized.

O5, declared agent policy, context and never scored. robots.txt directives for general and named AI agents, noai meta tags, and llms.txt presence. This separates "chose to exclude agents" from "broken for agents."

Consent overlays, recorded and never scored. Consent management platform scripts are recorded as context, and a rendered full viewport overlay containing consent vocabulary is recorded as a flag. Consent gates are strongly region dependent and the runners are US based, so this signal is reported descriptively only.

## The score

Each site gets an Agent Accessibility Score from 0 to 100. It starts at 100 with fixed penalties, O1 minus 60, O2 minus 30, O3 minus 20, O4 minus 40, floored at 0. Flags recorded as not assessed contribute no penalty. The penalty table is frozen before the scan in config/penalties.json, and all raw flags are published so anyone can re-weight.

## Site sample

The sample comes from the Tranco list (tranco-list.eu), the standard research ranking, reduced to registrable (pay level) domains, with the exact list ID recorded in config/tranco-list-id.txt. Infrastructure domains with no meaningful homepage (CDN, ad tech, API, DNS) are excluded by the versioned list config/exclusions.csv with reasons, and the sample extends down the ranking until 5,000 real websites remain.

URL rules. For each domain, https on the apex is tried first, then https on www if the apex fails DNS or TLS, following up to 5 redirects, with no plain HTTP fallback. The final landing URL is recorded. Redirects landing on a different registrable domain are flagged and deduplicated in analysis so one site is never counted twice. Internationalized domains are fetched in punycode form. Homepages understate obstacles on inner pages, stated as a limitation.

## Request protocol and politeness

Per site, at most 6 top level fetches, of which one is a full browser render.

1. robots.txt, raw fetch.
2. llms.txt, raw fetch.
3. Homepage with a plain HTTP client and the declared agent user agent, AgentObstacleCourse/1.0 with the repository address and contact email.
4. Homepage with a plain HTTP client and a stock browser user agent, with the research contact still declared in a From header. This fetch exists to measure O3 without confounding O2.
5. One retry of a homepage fetch, only after a network error, never after an HTTP error response.
6. Homepage once in headless Chromium with its stock user agent. A browser render loads the page's subresources exactly like a normal page view, so the six fetch count refers to top level fetches and the render is the equivalent of one ordinary visit.

Politeness rules, hard coded.

- One scan pass total. A shard is re-run only after an infrastructure failure, and only that shard's sites are contacted again. No schedule exists, any re-run is a deliberate manual dispatch.
- robots.txt is fetched first and honored. If it disallows the homepage for all agents or for our named agent, fetches 3 to 6 are skipped and the site is classified as a declared exclusion, recorded under O5 and never scored as broken.
- Minimum 2 seconds between consecutive top level requests to the same site. Different sites interleave, so real per site spacing is much larger.
- 15 second timeout, no retries on HTTP errors, no form submission, no path probing beyond the two well known policy files, no attempt to bypass any obstacle. A bot wall is a result, never a challenge to defeat.
- Any site owner can be excluded on request, and the contact email travels in every request.

## Outputs

1. data/census.csv, one row per site, with rank, domain, final URL, flags for O1 to O5 plus consent and the unreachable and declared exclusion states, score, category where known, and duplicate flags. Per site evidence lives in data/raw.
2. REPORT.md, obstacle prevalence overall and by rank band (top 100, 101 to 1,000, 1,001 to 5,000), score distribution, the declared exclusion versus broken split, and the O3 identity discrimination findings.
3. This document, frozen before the scan.

## Limitations

Stated plainly, and first among them the vantage point. The scan originates from cloud datacenter IP addresses, which bot protection treats far more harshly than residential traffic or established AI crawlers' published ranges, so O1 rates are an upper bound for an agent running in a datacenter, not a claim about every agent. Also, homepages only. A single snapshot in time. US egress undercounts regional consent gates, which is why consent is unscored. Signature lists make obstacle counts lower bounds. Tranco measures popularity, not importance.
