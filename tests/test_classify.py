"""Unit tests for src.classify against fixture responses.

No network, no Playwright, no third party packages required.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import classify

SIGNATURES, PENALTIES = classify.load_config()

CLOUDFLARE_CHALLENGE_HTML = """
<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body><div id="challenge"><p>Checking your browser before accessing example.com.</p>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate.js"></script>
<p>Cloudflare Ray ID: 8abc123</p></div></body></html>
"""

NORMAL_HTML = """
<!DOCTYPE html><html><head><title>Acme</title><style>body{color:red}</style></head>
<body><h1>Welcome to Acme</h1><p>%s</p>
<script>console.log('ignored')</script></body></html>
""" % ("We sell widgets and write long articles about widgets. " * 30)

JS_SHELL_HTML = """
<!DOCTYPE html><html><head><title>App</title></head>
<body><div id="root"></div><script src="/bundle.js"></script></body></html>
"""

LOGIN_REDIRECT_URL = "https://example.com/accounts/login"


def fetch(status=200, body=NORMAL_HTML, headers=None, final_url="https://example.com/", error=None):
    return {"status": status, "headers": headers or {}, "body": body,
            "text": classify.extract_text(body), "final_url": final_url, "error": error}


def evidence(**overrides):
    base = {
        "state": "scanned",
        "robots": {"status": 200, "body": "User-agent: *\nDisallow:\n"},
        "llms_txt": {"present": False},
        "fetch_agent": fetch(),
        "fetch_browser": fetch(),
        "render": {"ok": True, "status": 200, "headers": {},
                   "text": classify.extract_text(NORMAL_HTML),
                   "final_url": "https://example.com/",
                   "consent_overlay": False, "login_dom": False},
    }
    base.update(overrides)
    return base


def run(**overrides):
    return classify.classify_site(evidence(**overrides), SIGNATURES, PENALTIES)


class TestBotWall(unittest.TestCase):
    def test_cloudflare_challenge_fixture_is_o1(self):
        vendor = classify.detect_bot_wall(403, {}, CLOUDFLARE_CHALLENGE_HTML, SIGNATURES)
        self.assertEqual(vendor, "cloudflare")

    def test_challenge_body_without_challenge_status_is_not_o1(self):
        self.assertIsNone(classify.detect_bot_wall(200, {}, CLOUDFLARE_CHALLENGE_HTML, SIGNATURES))

    def test_403_without_signature_is_not_o1(self):
        self.assertIsNone(classify.detect_bot_wall(403, {}, "<html>Forbidden</html>", SIGNATURES))

    def test_cf_mitigated_header_is_o1(self):
        vendor = classify.detect_bot_wall(200, {"CF-Mitigated": "challenge"}, "", SIGNATURES)
        self.assertEqual(vendor, "cloudflare")

    def test_o1_flag_set_on_agent_fetch_wall(self):
        result = run(fetch_agent=fetch(status=403, body=CLOUDFLARE_CHALLENGE_HTML))
        self.assertTrue(result["o1"])
        self.assertEqual(result["o1_vendor"], "cloudflare")


class TestO1Precedence(unittest.TestCase):
    def test_wall_on_all_variants_makes_o2_o3_o4_not_assessed(self):
        walled = fetch(status=403, body=CLOUDFLARE_CHALLENGE_HTML)
        result = run(fetch_agent=walled, fetch_browser=dict(walled),
                     render={"ok": True, "status": 403, "headers": {},
                             "body": CLOUDFLARE_CHALLENGE_HTML,
                             "text": classify.extract_text(CLOUDFLARE_CHALLENGE_HTML),
                             "final_url": "https://example.com/",
                             "consent_overlay": False, "login_dom": False})
        self.assertTrue(result["o1"])
        for key in ("o2", "o3", "o4"):
            self.assertEqual(result[key], classify.NOT_ASSESSED, key)

    def test_wall_on_one_variant_still_assesses_others(self):
        result = run(fetch_agent=fetch(status=403, body=CLOUDFLARE_CHALLENGE_HTML))
        self.assertTrue(result["o1"])
        self.assertNotEqual(result["o4"], classify.NOT_ASSESSED)


class TestO2(unittest.TestCase):
    def test_js_shell_page_is_o2(self):
        rendered = "Rendered application text. " * 40  # over 500 chars
        result = run(fetch_agent=fetch(body=JS_SHELL_HTML),
                     fetch_browser=fetch(body=JS_SHELL_HTML),
                     render={"ok": True, "status": 200, "headers": {}, "text": rendered,
                             "final_url": "https://example.com/",
                             "consent_overlay": False, "login_dom": False})
        self.assertTrue(result["o2"])

    def test_full_raw_page_is_not_o2(self):
        self.assertFalse(run()["o2"])

    def test_tiny_rendered_text_is_not_o2(self):
        result = run(fetch_agent=fetch(body=JS_SHELL_HTML),
                     fetch_browser=fetch(body=JS_SHELL_HTML),
                     render={"ok": True, "status": 200, "headers": {}, "text": "short",
                             "final_url": "https://example.com/",
                             "consent_overlay": False, "login_dom": False})
        self.assertFalse(result["o2"])

    def test_o2_not_assessed_when_raw_browser_fetch_walled(self):
        result = run(fetch_browser=fetch(status=403, body=CLOUDFLARE_CHALLENGE_HTML))
        self.assertEqual(result["o2"], classify.NOT_ASSESSED)


class TestO3(unittest.TestCase):
    def test_differing_status_class_is_o3(self):
        result = run(fetch_agent=fetch(status=403, body="<html>Forbidden</html>"))
        self.assertTrue(result["o3"])

    def test_text_ratio_under_half_is_o3(self):
        result = run(fetch_agent=fetch(body="<html><body>tiny</body></html>"))
        self.assertTrue(result["o3"])

    def test_identical_responses_are_not_o3(self):
        self.assertFalse(run()["o3"])


class TestO4(unittest.TestCase):
    def test_401_is_o4(self):
        result = run(fetch_agent=fetch(status=401), fetch_browser=fetch(status=401))
        self.assertTrue(result["o4"])

    def test_redirect_to_login_path_is_o4(self):
        result = run(fetch_browser=fetch(final_url=LOGIN_REDIRECT_URL))
        self.assertTrue(result["o4"])
        self.assertIsNotNone(result["o4_caveat"])

    def test_login_dom_flag_is_o4(self):
        result = run(render={"ok": True, "status": 200, "headers": {},
                             "text": "Sign in", "final_url": "https://example.com/",
                             "consent_overlay": False, "login_dom": True})
        self.assertTrue(result["o4"])

    def test_normal_page_is_not_o4(self):
        self.assertFalse(run()["o4"])


class TestRobotsAndStates(unittest.TestCase):
    def test_robots_disallow_root_for_star(self):
        parsed = classify.parse_robots("User-agent: *\nDisallow: /\n")
        self.assertTrue(parsed["disallows_home"])

    def test_robots_disallow_root_for_our_token(self):
        parsed = classify.parse_robots(
            "User-agent: AgentObstacleCourse\nDisallow: /\n\nUser-agent: *\nDisallow:\n")
        self.assertTrue(parsed["disallows_home"])

    def test_robots_partial_disallow_is_not_exclusion(self):
        parsed = classify.parse_robots("User-agent: *\nDisallow: /admin\n")
        self.assertFalse(parsed["disallows_home"])

    def test_robots_records_ai_directives(self):
        parsed = classify.parse_robots("User-agent: GPTBot\nDisallow: /\n")
        self.assertIn("gptbot", parsed["ai_directives"])

    def test_declared_exclusion_state_is_not_scored(self):
        result = run(state="declared_exclusion", fetch_agent=None,
                     fetch_browser=None, render=None)
        self.assertEqual(result["state"], "declared_exclusion")
        self.assertIsNone(result["score"])
        self.assertEqual(result["o1"], classify.NOT_ASSESSED)

    def test_unreachable_state_is_not_scored(self):
        result = run(state="unreachable", fetch_agent=None, fetch_browser=None, render=None)
        self.assertIsNone(result["score"])


class TestScore(unittest.TestCase):
    def test_clean_site_scores_100(self):
        self.assertEqual(run()["score"], 100)

    def test_single_penalties(self):
        cases = {"o1": 40, "o2": 70, "o3": 80, "o4": 60}
        for flag, expected in cases.items():
            flags = {"state": "scanned", "o1": False, "o2": False,
                     "o3": False, "o4": False, flag: True}
            self.assertEqual(classify.compute_score(flags, PENALTIES), expected, flag)

    def test_floor_at_zero(self):
        flags = {"state": "scanned", "o1": True, "o2": True, "o3": True, "o4": True}
        self.assertEqual(classify.compute_score(flags, PENALTIES), 0)

    def test_not_assessed_contributes_no_penalty(self):
        flags = {"state": "scanned", "o1": True, "o2": classify.NOT_ASSESSED,
                 "o3": classify.NOT_ASSESSED, "o4": classify.NOT_ASSESSED}
        self.assertEqual(classify.compute_score(flags, PENALTIES), 40)


class TestHelpers(unittest.TestCase):
    def test_extract_text_skips_script_and_style(self):
        text = classify.extract_text(NORMAL_HTML)
        self.assertIn("Welcome to Acme", text)
        self.assertNotIn("console.log", text)
        self.assertNotIn("color:red", text)

    def test_consent_cmp_scripts_recorded_not_scored(self):
        body = NORMAL_HTML.replace("</head>",
                                   '<script src="https://cdn.cookielaw.org/x.js"></script></head>')
        result = run(fetch_browser=fetch(body=body))
        self.assertIn("cdn.cookielaw.org", result["consent"]["cmp_scripts"])
        self.assertEqual(result["score"], 100)  # consent never penalized


if __name__ == "__main__":
    unittest.main()
