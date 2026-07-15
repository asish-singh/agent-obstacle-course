"""Obstacle classification. Pure functions over saved evidence.

Every function here takes plain data (dicts, strings) and returns plain data,
so the whole module runs without network access, Playwright, or requests.
Detection rules come from config/signatures.json and the score table from
config/penalties.json, both loaded by the caller or via load_config().
"""

import json
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")

NOT_ASSESSED = "not_assessed"

# Named AI agent tokens looked for in robots.txt for the O5 record.
AI_AGENT_TOKENS = [
    "gptbot", "chatgpt-user", "oai-searchbot", "claudebot", "claude-web",
    "anthropic-ai", "google-extended", "perplexitybot", "ccbot", "bytespider",
    "amazonbot", "applebot-extended", "meta-externalagent", "cohere-ai",
]


def load_config(config_dir=CONFIG_DIR):
    with open(os.path.join(config_dir, "signatures.json"), encoding="utf-8") as f:
        signatures = json.load(f)
    with open(os.path.join(config_dir, "penalties.json"), encoding="utf-8") as f:
        penalties = json.load(f)
    return signatures, penalties


class _TextExtractor(HTMLParser):
    """Extract readable text from HTML, skipping script/style/template/noscript."""

    SKIP = {"script", "style", "template", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self):
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()


def extract_text(html):
    """Readable text from raw HTML. Whitespace normalized."""
    if not html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.text()


def detect_bot_wall(status, headers, body, signatures):
    """Return the matching vendor name, or None.

    A bot wall requires a challenge status code (403/429/503) combined with a
    known challenge signature in the body, or a definitive challenge header.
    """
    rules = signatures["bot_wall"]
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    body_lower = (body or "").lower()
    for rule in rules.get("header_signatures", []):
        value = headers.get(rule["header"].lower())
        if value is not None:
            if any(p in value.lower() for p in rule["patterns"]):
                return rule["vendor"]
    if status not in rules["status_codes"]:
        return None
    for rule in rules.get("body_signatures", []):
        if any(p in body_lower for p in rule["patterns"]):
            return rule["vendor"]
    return None


def status_class(status):
    """2 for 2xx, 3 for 3xx, etc. None for missing/no response."""
    if status is None:
        return None
    return status // 100


def text_ratio(smaller_text, larger_text):
    """Length ratio of two texts, min over max. 1.0 when both empty."""
    a, b = len(smaller_text or ""), len(larger_text or "")
    if a == 0 and b == 0:
        return 1.0
    if max(a, b) == 0:
        return 1.0
    return min(a, b) / max(a, b)


def is_login_path(url, signatures):
    if not url:
        return False
    path = urlsplit(url).path.lower().rstrip("/") or "/"
    return any(path == p or path.startswith(p + "/") or path.endswith(p)
               for p in (pat.lower() for pat in signatures["login"]["path_patterns"]))


def detect_noai_meta(html):
    """True when a robots meta tag declares noai or noimageai."""
    if not html:
        return False
    for m in re.finditer(r"<meta\b[^>]*>", html, re.IGNORECASE):
        tag = m.group(0).lower()
        if "robots" in tag or "noai" in tag:
            if "noai" in tag or "noimageai" in tag:
                return True
    return False


def parse_robots(body, our_token="agentobstaclecourse"):
    """Parse robots.txt text.

    Returns a dict with:
      disallows_home: True when '/' is disallowed for '*' or for our UA token
      ai_directives: list of named AI agents that have any Disallow rule
    Manual parser so we can inspect per-agent groups; stdlib robotparser is
    also used by the fetcher as a cross check.
    """
    groups = {}  # agent token -> list of disallow paths
    current_agents = []
    expecting_agents = True
    for raw_line in (body or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            token = value.lower()
            if expecting_agents:
                current_agents.append(token)
            else:
                current_agents = [token]
                expecting_agents = True
            groups.setdefault(token, [])
        elif field in ("disallow", "allow"):
            expecting_agents = False
            if field == "disallow" and value:
                for agent in current_agents:
                    groups.setdefault(agent, []).append(value)
        else:
            expecting_agents = False

    def home_blocked(paths):
        return any(p == "/" or p == "/*" for p in paths)

    disallows_home = False
    for token in ("*", our_token):
        for agent, paths in groups.items():
            if agent == token or (token != "*" and token in agent):
                if home_blocked(paths):
                    disallows_home = True
    ai_directives = sorted(
        agent for agent, paths in groups.items()
        if paths and any(t in agent for t in AI_AGENT_TOKENS)
    )
    return {"disallows_home": disallows_home, "ai_directives": ai_directives}


def classify_site(evidence, signatures, penalties):
    """Classify one site's saved evidence into flags and a score.

    Evidence schema (produced by shard.py):
      state: scanned | unreachable | declared_exclusion
      robots: {status, body}                     (optional)
      llms_txt: {present}                        (optional)
      fetch_agent:   {status, headers, body, text, final_url, error}
      fetch_browser: {status, headers, body, text, final_url, error}
      render: {ok, text, consent_overlay, login_dom, final_url}  (optional)
      consent: {cmp_scripts}                     (optional)

    Returns flags dict with o1, o2, o3, o4 in {True, False, "not_assessed"},
    o5 record, consent record, state, and score (int or None).
    """
    state = evidence.get("state", "scanned")
    result = {
        "state": state,
        "o1": False, "o2": False, "o3": False, "o4": False,
        "o1_vendor": None,
        "o5": {}, "consent": {}, "o4_caveat": None,
        "score": None,
    }

    # O5 and consent are recorded even for declared exclusions.
    robots = evidence.get("robots") or {}
    parsed_robots = parse_robots(robots.get("body", "")) if robots.get("body") else {
        "disallows_home": False, "ai_directives": []}
    agent_body = (evidence.get("fetch_agent") or {}).get("body", "")
    browser_body = (evidence.get("fetch_browser") or {}).get("body", "")
    result["o5"] = {
        "robots_disallows_home": parsed_robots["disallows_home"],
        "robots_ai_directives": parsed_robots["ai_directives"],
        "noai_meta": detect_noai_meta(agent_body) or detect_noai_meta(browser_body),
        "llms_txt": bool((evidence.get("llms_txt") or {}).get("present")),
    }
    render = evidence.get("render") or {}
    result["consent"] = {
        "cmp_scripts": sorted(
            d for d in signatures["cmp_script_domains"]
            if d in (agent_body or "").lower() or d in (browser_body or "").lower()
        ),
        "overlay": bool(render.get("consent_overlay")),
    }

    if state != "scanned":
        result["o1"] = result["o2"] = result["o3"] = result["o4"] = NOT_ASSESSED
        return result

    fa = evidence.get("fetch_agent") or {}
    fb = evidence.get("fetch_browser") or {}

    wall_agent = detect_bot_wall(fa.get("status"), fa.get("headers"), fa.get("body"), signatures)
    wall_browser = detect_bot_wall(fb.get("status"), fb.get("headers"), fb.get("body"), signatures)
    render_ok = bool(render.get("ok"))
    wall_render = None
    if render_ok:
        wall_render = detect_bot_wall(render.get("status"), render.get("headers"),
                                      render.get("body") or render.get("text"), signatures)

    walls = [wall_agent, wall_browser] + ([wall_render] if render_ok else [])
    result["o1"] = any(walls)
    result["o1_vendor"] = next((w for w in walls if w), None)
    walled_on_all_variants = bool(walls) and all(walls)

    if walled_on_all_variants:
        result["o2"] = result["o3"] = result["o4"] = NOT_ASSESSED
    else:
        # O2, JS dependency. Assessed only when the raw (stock UA) fetch was
        # not bot walled and a render is available.
        if wall_browser or not render_ok:
            result["o2"] = NOT_ASSESSED if wall_browser else False
        else:
            raw_text = fb.get("text") or ""
            rendered_text = render.get("text") or ""
            if len(rendered_text) > 500:
                ratio = len(raw_text) / len(rendered_text)
                result["o2"] = ratio < 0.2
            else:
                result["o2"] = False

        # O3, identity discrimination on the two raw fetches.
        ca, cb = status_class(fa.get("status")), status_class(fb.get("status"))
        if ca is None or cb is None:
            result["o3"] = NOT_ASSESSED
        elif ca != cb:
            result["o3"] = True
        else:
            result["o3"] = text_ratio(fa.get("text") or "", fb.get("text") or "") < 0.5

        # O4, login wall.
        o4 = False
        for fetch in (fa, fb):
            if fetch.get("status") == 401:
                o4 = True
            if is_login_path(fetch.get("final_url"), signatures):
                o4 = True
        if render_ok:
            if render.get("login_dom"):
                o4 = True
            if is_login_path(render.get("final_url"), signatures):
                o4 = True
        result["o4"] = o4
        if o4:
            result["o4_caveat"] = ("Homepage login walls are flagged mechanically; "
                                   "for many SaaS domains the homepage legitimately is a login page.")

    result["score"] = compute_score(result, penalties)
    return result


def compute_score(flags, penalties):
    """Agent Accessibility Score. Starts at base, fixed penalties, floored.

    not_assessed flags contribute no penalty. Unscored states return None.
    """
    if flags.get("state") != "scanned":
        return None
    score = penalties["base_score"]
    for key, penalty in penalties["penalties"].items():
        if flags.get(key.lower()) is True:
            score -= penalty
    return max(score, penalties["floor"])
