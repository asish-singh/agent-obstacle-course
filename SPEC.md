# The Agent Obstacle Course, Research Specification

**Working title:** How usable is the web for AI agents? A one time census of 5,000 sites.
**Status:** Specification v1.1, 15 July 2026, revised after independent QC review
**Author:** Asish Singh
**Cost:** Zero. One time scan on GitHub Actions (free on public repos). No AI API calls.

## 1. Research question

Everyone benchmarks AI agents. Nobody benchmarks the websites they must operate on. This study measures, for 5,000 of the world's most popular websites, how many obstacles stand between a well behaved non browser agent and the site's content, as seen from cloud datacenter infrastructure (the vantage point stated plainly, see section 6).

Primary question. What fraction of these sites can a non browser agent actually read, and what stops it on the rest?

Secondary questions.
1. Which obstacle is most common, bot walls, JavaScript only pages, login walls, or identity based discrimination?
2. How does agent accessibility vary by popularity rank band and, where category data exists, by site category?
3. Do sites that exclude agents by declared policy differ from sites that are merely broken for them?

## 2. What counts as an obstacle

Each site receives a small number of polite page fetches (section 4), and the responses are classified against these types. Everything is mechanical, no AI judging, every classification traceable to saved evidence. Concrete detection rules live in versioned `config/signatures.json`; the descriptions below are the human summary.

**O1. Bot wall.** The fetch returns a challenge instead of content. Detected by status 403/429/503 combined with known challenge signatures (Cloudflare, Akamai, PerimeterX, DataDome, hCaptcha/reCAPTCHA interstitials). Precedence rule, if O1 fires on all fetch variants, obstacles O2 to O4 are recorded as "not assessed," never as zero or as additional penalties.

**O2. JavaScript dependency.** The raw HTML contains almost no readable text but a rendered browser sees a full page. Measured as extracted text ratio, raw versus rendered, classified JS dependent when the ratio is under 0.2 and rendered text exceeds 500 characters. Assessed only when the raw fetch was not bot walled (see O1 precedence). Both text extracts are saved (truncated to 20 KB) so every ratio is reproducible.

**O3. Identity discrimination.** The site serves substantially different responses to the declared agent UA versus a stock browser UA on the plain fetches (different status class, or text ratio between the two raw fetches under 0.5). This separates "the site needs JavaScript" from "the site treats non browser identities differently," which the QC review flagged as a confound; measuring it required adding one fetch (section 4).

**O4. Login wall.** The homepage or its redirect target demands authentication. Mechanical rule, HTTP 401, redirect chain ending at a path matching a versioned login pattern list, or a rendered DOM whose largest above the fold container includes a password input while total article-like text is under 500 characters. Caveat recorded per site, for many SaaS domains the homepage legitimately is a login page; these are flagged, not moralized.

**O5. Declared agent policy (context, not scored).** robots.txt directives for general and named AI agents, noai meta tags, llms.txt presence. This separates "chose to exclude agents" from "broken for agents" in the analysis.

**Consent overlays (recorded, not scored).** Consent management platform scripts are recorded as context, and a rendered full viewport overlay with consent vocabulary is recorded as a flag. Per QC, consent gates are strongly region dependent and the runners are US based, so this signal is reported descriptively but excluded from the score.

**The score.** Each site gets an Agent Accessibility Score from 0 to 100, starting at 100 with fixed penalties, O1 minus 60, O2 minus 30, O3 minus 20, O4 minus 40, floor at 0 (the floor and the "not assessed" rule are stated in the methodology). The penalty table is frozen before the scan in `config/penalties.json`, and all raw flags are published so anyone can re-weight.

## 3. Site sample

- **Source.** The Tranco list (tranco-list.eu), the standard research ranking, using the pay level domains variant so entries are registrable domains, with the exact list ID recorded in the repo for citation and reproducibility.
- **Sample.** The top 5,000 entries after applying a documented infrastructure exclusion, domains that are CDN, ad tech, API, or DNS infrastructure with no meaningful homepage (googleapis.com, doubleclick.net, root-servers.net and similar) are excluded by a versioned list plus a mechanical rule (no HTML homepage on apex or www), and the sample extends down the ranking until 5,000 real websites remain. Excluded domains are published with reasons.
- **Categories.** Category labels from a public categorization source, recorded in the repo, will cover only part of the sample; category analysis is labeled partial coverage.
- **Unit and URL rules.** For each domain, try `https://apex` first, then `https://www.apex` if apex fails DNS or TLS, following up to 5 redirects, no plain HTTP fallback. The final landing URL is recorded; redirects that land on a different registrable domain (twitter.com to x.com) are flagged and deduplicated in analysis so one site is never counted twice. IDN domains are fetched in punycode form. Homepages understate obstacles on inner pages; stated as a limitation.

## 4. Request protocol and politeness

Per site, at most 6 page level fetches, of which one is a full browser render:

1. `robots.txt` (raw fetch)
2. `llms.txt` (raw fetch)
3. Homepage, plain HTTP client, declared agent UA `AgentObstacleCourse/1.0 (+repo URL; research; contact email)`
4. Homepage, plain HTTP client, stock browser UA, with the research contact still declared in a `From` header (needed to measure O3 without confounding O2)
5. One retry of a homepage fetch only after a network error, never after an HTTP error response
6. Homepage once in headless Chromium (Playwright) with its stock UA. Honesty note, a browser render loads the page's subresources (scripts, styles, images) exactly like a normal page view; the "6 fetches" count is top level fetches, and the render is the equivalent of one ordinary visit.

Politeness rules, hard coded.
- One scan pass total. A shard is re-run only after an infrastructure failure, and only that shard's sites are contacted again. No cron trigger exists; any re-run is a deliberate manual dispatch.
- robots.txt is fetched first and honored, if it disallows the homepage for `*` or for our named agent, fetches 3 to 6 are skipped and the site is classified `declared exclusion` (recorded under O5, not scored as broken).
- Minimum 2 seconds between consecutive top level requests to the same site; different sites interleave, so real per site spacing is much larger.
- 15 second timeout, no retries on HTTP errors, no form submission, no path probing beyond the two well known policy files, no attempt to bypass any obstacle. A bot wall is a result, never a challenge to defeat.
- Any site owner can be excluded on request; the contact email travels in every request.

This is low volume, honestly identified fetching of public homepages, a smaller footprint than a link preview bot, and each site is visited once.

## 5. Running it on GitHub Actions, one time, within limits

GitHub Actions facts (free plan, public repo, verified against GitHub's documentation on 15 July 2026): unlimited total minutes, 6 hour cap per job, 20 concurrent jobs account wide, 256 matrix jobs max, standard Linux runners have 4 vCPUs and 16 GB RAM, artifact storage is free for public repos with 90 day default retention. Scanning external sites consumes no GitHub API rate limits; the workflow's own GitHub API usage (artifact upload/download, one push) is trivial.

**Sharding plan.**
- One workflow, `census.yml`, manual trigger only (workflow_dispatch). No schedule exists.
- Matrix of 20 shard jobs x 250 sites = 5,000, chosen to fit the 20 concurrent job cap in a single wave (assuming no other workflows are running, which is under our control on census day).
- Within a shard, an async pool of 8 workers handles the plain fetches, and renders run 3 at a time (comfortable on 16 GB runners).
- Time budget, computed as max(fetch lane, render lane). Render lane is the bottleneck, 250 renders / 3 concurrent x 10 to 20 seconds each ≈ 14 to 28 minutes. Fetch lane worst case (every request timing out, 5 x 15 s plus retry ≈ 90 s per site serial) is 250 x 90 / 8 ≈ 47 minutes; realistic fetch lane is far lower since timeouts are the exception. Shard budget 30 to 50 minutes, versus a 6 hour cap, roughly a 7x safety margin even in the pathological case.
- Wall clock for the census, one wave plus the aggregator, roughly 1 to 1.5 hours; if another workflow happens to occupy job slots it stretches, it never fails.
- Each shard uploads results (one gzipped JSON per site, ~40 KB, ~10 MB per shard, ~200 MB total) as an artifact. The aggregator job (needs: all shards) merges, computes statistics, writes the dataset and report, and makes the single commit, so there are no push races. Artifacts are consumed immediately, retention is irrelevant, and the durable record is the git commit.

**Failure handling.** A site erroring on everything is classified `unreachable`, reported as its own bucket, never scored. A dead shard is re-run alone via GitHub's re-run failed jobs, idempotently.

## 6. Outputs

1. **Dataset.** `data/census.csv`, one row per site, rank, domain, final URL, flags for O1 to O5 plus consent and unreachable/declared exclusion states, score, category where known, and `data/raw/` holding per site evidence (status codes, headers, signature matches, truncated text extracts).
2. **Report.** `REPORT.md`, obstacle prevalence overall and by rank band (top 100, 101 to 1,000, 1,001 to 5,000), score distribution, the declared exclusion versus broken split, and the O3 identity discrimination findings, which are the most novel number in the study.
3. **Methodology.** `METHODOLOGY.md`, frozen before the scan, penalty table, signature lists, URL rules, all politeness rules.
4. **Limitations, stated plainly and first among them the vantage point.** The scan originates from cloud datacenter IPs, which bot protection treats far more harshly than residential traffic or established AI crawlers' published ranges, so O1 rates are an upper bound for "agent running in a datacenter" and not a claim about every agent. Also, homepages only; single snapshot; US egress undercounts regional consent gates (which is why consent is unscored); signature lists make obstacle counts lower bounds; Tranco measures popularity, not importance.

## 7. Repository layout

```
agent-obstacle-course/
  config/
    penalties.json        frozen score penalty table
    signatures.json       bot wall, login, CMP, overlay detection rules, versioned
    exclusions.csv        infrastructure domains excluded, with reasons
    sites.csv             Tranco slice (pay level domains variant, list ID recorded)
  src/
    fetcher.py            polite HTTP client, spacing, timeouts, both UA modes, punycode handling
    renderer.py           Playwright render, text extraction
    classify.py           obstacle classification, pure functions, O1 precedence logic
    shard.py              entry point, scans one shard by index
    aggregate.py          merge artifacts, dedupe cross domain landings, stats, report
  tests/                  unit tests for classify.py against fixture responses
  .github/workflows/
    census.yml            manual dispatch only, 20 shard matrix + aggregator
    validate.yml          tests on push
  data/                   filled by the census run
  REPORT.md               generated
  METHODOLOGY.md          frozen protocol
  README.md
```

## 8. Timeline

| Step | What happens |
|---|---|
| Build | Repo, fetcher, classifier, tests green, methodology frozen |
| Pilot | Manual dispatch on a 50 site pilot shard, classifications verified by hand against saved evidence, signature lists tuned once, before freezing |
| Census | One dispatch, 20 shards, aggregate, dataset and report committed |
| Writeup | Findings narrative in the repo, every claim traceable to census.csv |

## Appendix, QC review outcome

An independent review checked v1.0's arithmetic, GitHub Actions claims, methodology, and ethics. It confirmed the platform limits, the artifact math, Tranco as the right source, and that a one time, low volume, honestly identified census is acceptable use of Actions. It found 15 defects (3 blocking), all addressed in this version, the honest fetch accounting including render subresources, the datacenter vantage point limitation, the O1/O2/O3 confound resolved via the added stock UA fetch and precedence rules, corrected time and wall clock math, one wave sharding, robots.txt now honored, infrastructure domain exclusions, redirect and IDN rules, consent removed from scoring, concrete login wall rules, 16 GB runner facts, and reconciled contacted once wording.
