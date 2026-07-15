"""REP matching tests for classify.parse_robots / robots_path_allowed.

Fixture bodies under tests/fixtures/ are the actual robots.txt responses
saved by the 50 site pilot (data/pilot/*.json.gz).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import classify

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class TestPilotFixtures(unittest.TestCase):
    def test_google_allows_home(self):
        # Pilot misclassified google.com as declared_exclusion via the
        # stdlib parser; the REP verdict for '/' is allowed.
        body = fixture("robots_google.com.txt")
        self.assertTrue(classify.robots_path_allowed(body, "/"))
        self.assertFalse(classify.parse_robots(body)["disallows_home"])

    def test_facebook_disallows_home(self):
        body = fixture("robots_facebook.com.txt")
        self.assertTrue(classify.parse_robots(body)["disallows_home"])

    def test_netflix_disallows_home(self):
        body = fixture("robots_netflix.com.txt")
        self.assertTrue(classify.parse_robots(body)["disallows_home"])

    def test_myfritz_allows_home(self):
        # 'Disallow: /' plus 'Allow: /$' allows the homepage under the
        # longest match rule ('/$' is longer than '/').
        body = fixture("robots_myfritz.net.txt")
        self.assertFalse(classify.parse_robots(body)["disallows_home"])


class TestSyntheticRep(unittest.TestCase):
    def test_dollar_anchor_allows_exact_home(self):
        body = "User-agent: *\nDisallow: /\nAllow: /$\n"
        self.assertTrue(classify.robots_path_allowed(body, "/"))
        self.assertFalse(classify.robots_path_allowed(body, "/page"))

    def test_dollar_anchor_disallow_only_home(self):
        body = "User-agent: *\nDisallow: /$\n"
        self.assertFalse(classify.robots_path_allowed(body, "/"))
        self.assertTrue(classify.robots_path_allowed(body, "/page"))

    def test_wildcard_matches_home(self):
        body = "User-agent: *\nDisallow: /*\n"
        self.assertFalse(classify.robots_path_allowed(body, "/"))

    def test_wildcard_mid_pattern(self):
        body = "User-agent: *\nDisallow: /a*z\n"
        self.assertFalse(classify.robots_path_allowed(body, "/abcz"))
        self.assertTrue(classify.robots_path_allowed(body, "/abc"))

    def test_longest_match_tie_allow_wins(self):
        body = "User-agent: *\nDisallow: /\nAllow: /\n"
        self.assertTrue(classify.robots_path_allowed(body, "/"))

    def test_longer_disallow_beats_shorter_allow(self):
        body = "User-agent: *\nAllow: /\nDisallow: /p\n"
        self.assertFalse(classify.robots_path_allowed(body, "/page"))

    def test_named_agent_group_overrides_star(self):
        body = ("User-agent: AgentObstacleCourse\nDisallow: /\n\n"
                "User-agent: *\nDisallow:\n")
        self.assertTrue(classify.parse_robots(body)["disallows_home"])

    def test_named_agent_group_allows_while_star_blocks(self):
        body = ("User-agent: AgentObstacleCourse\nAllow: /\n\n"
                "User-agent: *\nDisallow: /\n")
        self.assertFalse(classify.parse_robots(body)["disallows_home"])

    def test_no_matching_rule_is_allowed(self):
        self.assertTrue(classify.robots_path_allowed("User-agent: *\nDisallow: /admin\n", "/"))

    def test_empty_body_is_allowed(self):
        self.assertTrue(classify.robots_path_allowed("", "/"))


if __name__ == "__main__":
    unittest.main()
