"""Polite HTTP client for the census. SPEC.md section 4 rules, hard coded.

Per site, top level requests in order: robots.txt, llms.txt, homepage with the
declared agent UA, homepage with a stock browser UA (plus a From header).
Minimum 2 seconds between consecutive top level requests to the same site.
15 second timeout, one retry only after a network error, never after an HTTP
error response. https apex first, then https www on DNS or TLS failure. Max 5
redirects, no plain HTTP fallback. IDN domains are fetched in punycode form.
"""

import time
from urllib.parse import urlsplit
from urllib import robotparser

import requests

try:
    from src import classify
except ImportError:
    import classify

try:
    import tldextract
    _EXTRACT = tldextract.TLDExtract(suffix_list_urls=())  # offline snapshot
except ImportError:  # classification and tests never need this
    tldextract = None
    _EXTRACT = None

AGENT_UA = ("AgentObstacleCourse/1.0 "
            "(+https://github.com/asish-singh/agent-obstacle-course; "
            "research; asish-singh@x-b-e.com)")
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")
CONTACT_EMAIL = "asish-singh@x-b-e.com"
OUR_ROBOTS_TOKEN = "AgentObstacleCourse"

TIMEOUT = 15
MIN_SPACING = 2.0
MAX_REDIRECTS = 5
BODY_LIMIT = 512 * 1024  # keep at most 512 KB of any body


def to_punycode(domain):
    """IDN domain to its punycode (ASCII) form."""
    try:
        return domain.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        return domain


def registrable_domain(host):
    """Registrable (pay level) domain of a hostname."""
    if not host:
        return ""
    host = host.lower().rstrip(".")
    if _EXTRACT is not None:
        ext = _EXTRACT(host)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


class SiteFetcher:
    """Fetches all raw resources for one site, honoring the politeness rules."""

    def __init__(self, domain):
        self.domain = to_punycode(domain)
        self.session = requests.Session()
        self.session.max_redirects = MAX_REDIRECTS
        self._last_request_at = 0.0
        self.host = None  # apex or www.apex, decided by the first fetch

    def _space(self):
        wait = self._last_request_at + MIN_SPACING - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _get(self, url, user_agent, extra_headers=None, retry=True):
        """One top level GET. Returns an evidence dict, never raises."""
        self._space()
        headers = {"User-Agent": user_agent,
                   "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                   "Accept-Language": "en-US,en;q=0.9"}
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = self.session.get(url, headers=headers, timeout=TIMEOUT,
                                    allow_redirects=True, stream=True)
            body = resp.raw.read(BODY_LIMIT, decode_content=True)
            resp.close()
            try:
                text_body = body.decode(resp.encoding or "utf-8", errors="replace")
            except LookupError:
                text_body = body.decode("utf-8", errors="replace")
            return {
                "url": url,
                "final_url": resp.url,
                "status": resp.status_code,
                "headers": dict(resp.headers),
                "body": text_body,
                "error": None,
            }
        except requests.exceptions.TooManyRedirects:
            return {"url": url, "final_url": None, "status": None,
                    "headers": {}, "body": "", "error": "too_many_redirects"}
        except requests.exceptions.RequestException as exc:
            if retry:
                return self._get(url, user_agent, extra_headers, retry=False)
            return {"url": url, "final_url": None, "status": None,
                    "headers": {}, "body": "", "error": type(exc).__name__}

    def _resolve_host(self):
        """Try https apex, then https www, on DNS or TLS failure only."""
        for host in (self.domain, "www." + self.domain):
            result = self._get(f"https://{host}/robots.txt", AGENT_UA)
            if result["error"] in ("ConnectionError", "SSLError", "ConnectTimeout"):
                continue
            self.host = host
            return result
        self.host = None
        return result  # last failure, recorded as evidence

    def fetch_all(self):
        """Run the full raw protocol for this site. Returns evidence dict."""
        evidence = {"domain": self.domain}

        robots_result = self._resolve_host()
        evidence["robots"] = {
            "status": robots_result["status"],
            "body": robots_result["body"][:65536] if robots_result["status"] == 200 else "",
            "error": robots_result["error"],
        }
        if robots_result["status"] == 200:
            evidence["robots"]["robots_stdlib_opinion"] = (
                self._robots_stdlib_opinion(robots_result["body"]))
        if self.host is None:
            evidence["state"] = "unreachable"
            evidence["error"] = robots_result["error"]
            return evidence

        base = f"https://{self.host}"

        if robots_result["status"] == 200 and self._robots_disallows_home(robots_result["body"]):
            evidence["state"] = "declared_exclusion"
            return evidence

        llms = self._get(f"{base}/llms.txt", AGENT_UA)
        evidence["llms_txt"] = {
            "status": llms["status"],
            "present": llms["status"] == 200 and self._looks_like_text(llms),
        }

        fa = self._get(base + "/", AGENT_UA)
        fb = self._get(base + "/", BROWSER_UA, extra_headers={"From": CONTACT_EMAIL})
        evidence["fetch_agent"] = self._trim(fa)
        evidence["fetch_browser"] = self._trim(fb)

        if fa["error"] and fb["error"]:
            evidence["state"] = "unreachable"
            evidence["error"] = fa["error"]
        else:
            evidence["state"] = "scanned"

        evidence["cross_domain_landing"] = None
        for fetch in (fa, fb):
            if fetch["final_url"]:
                landed = registrable_domain(urlsplit(fetch["final_url"]).hostname or "")
                if landed and landed != registrable_domain(self.domain):
                    evidence["cross_domain_landing"] = landed
        evidence["homepage_url"] = base + "/"
        return evidence

    @staticmethod
    def _looks_like_text(result):
        ctype = result["headers"].get("Content-Type", "").lower()
        body = result["body"].lstrip().lower()
        return "html" not in ctype and not body.startswith("<!doctype") and not body.startswith("<html")

    @staticmethod
    def _trim(result):
        result = dict(result)
        result["body"] = (result["body"] or "")[:BODY_LIMIT]
        return result

    def _robots_disallows_home(self, body):
        """robots.txt honored. classify.parse_robots is the single authority.

        The same function computes o5.robots_disallows_home during
        classification, so the declared_exclusion state and the o5 field can
        never contradict each other.
        """
        return classify.parse_robots(body, our_token=OUR_ROBOTS_TOKEN.lower())["disallows_home"]

    def _robots_stdlib_opinion(self, body):
        """Stdlib robotparser verdict, recorded as evidence only, never deciding.

        The stdlib parser has proven version unstable across Python releases,
        so it is kept purely as a cross check in the evidence JSON.
        """
        try:
            rp = robotparser.RobotFileParser()
            rp.parse(body.splitlines())
            return (not rp.can_fetch(OUR_ROBOTS_TOKEN, f"https://{self.host}/")
                    or not rp.can_fetch(AGENT_UA, f"https://{self.host}/"))
        except Exception:
            return None
