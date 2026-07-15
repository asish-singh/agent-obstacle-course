# Project: agent-obstacle-course

A one time census of 5,000 popular websites measuring what stops a well behaved AI agent from reading them, run entirely on GitHub Actions at zero cost.

## Status

- Started: 2026-07-15
- Current state: building toward the 50 site pilot

## Goal

A public dataset and report answering how usable the web is for non browser agents, with every classification traceable to committed evidence. Full protocol in SPEC.md, frozen as METHODOLOGY.md before the census.

## How to run it

- Tests: `python3 -m unittest discover -s tests`
- Pilot: dispatch `census.yml` with pilot=true (50 sites, shard 0 only)
- Census: dispatch `census.yml` with pilot=false, one time only

## Notes for Claude

- Asish is non-technical: explain in plain language, choose sensible defaults, confirm before anything destructive.
- METHODOLOGY.md freezes after the pilot; later edits must be deliberate visible commits.
- Politeness rules in SPEC.md section 4 are non-negotiable, honest UA with contact email, robots.txt honored, one scan pass, never challenge a bot wall.
- The census runs once. Never add a schedule trigger to census.yml.
- Repo is public; commit messages are for a public audience.
