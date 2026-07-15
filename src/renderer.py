"""Playwright render of one homepage. One ordinary browser visit, stock UA.

Extracts rendered text, detects a full viewport consent overlay, and applies
the mechanical login DOM rule from config/signatures.json. Import of
Playwright is deferred so classify.py and its tests never need it.
"""

TEXT_LIMIT = 20 * 1024  # saved text extracts are truncated to 20 KB
NAV_TIMEOUT_MS = 20000
VIEWPORT = {"width": 1280, "height": 900}

_OVERLAY_JS = """
(args) => {
  const vocab = args.vocab;
  const coverage = args.coverage;
  const vw = window.innerWidth, vh = window.innerHeight;
  for (const el of document.querySelectorAll('body *')) {
    const style = getComputedStyle(el);
    if (style.position !== 'fixed' && style.position !== 'absolute') continue;
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width < vw * coverage || r.height < vh * coverage) continue;
    const text = (el.innerText || '').toLowerCase();
    if (vocab.some(v => text.includes(v))) return true;
  }
  return false;
}
"""

_LOGIN_JS = """
(args) => {
  const fold = args.fold, maxChars = args.maxChars;
  const pw = Array.from(document.querySelectorAll('input[type=password]'))
    .filter(el => el.getBoundingClientRect().top < fold);
  if (pw.length === 0) return false;
  // Largest above the fold container by area.
  let largest = null, largestArea = 0;
  for (const el of document.querySelectorAll('body, body *')) {
    const r = el.getBoundingClientRect();
    if (r.top >= fold) continue;
    const area = r.width * Math.min(r.height, fold - Math.max(r.top, 0));
    if (area > largestArea) { largestArea = area; largest = el; }
  }
  if (!largest || !pw.some(el => largest.contains(el))) return false;
  const articleText = Array.from(document.querySelectorAll('article, main, p, h1, h2, h3, li'))
    .map(el => el.innerText || '').join(' ').trim();
  return articleText.length < maxChars;
}
"""


def render_homepage(url, signatures, browser=None):
    """Render one homepage. Returns an evidence dict, never raises.

    Pass an existing Playwright browser to reuse it across sites; otherwise a
    fresh Chromium is launched and closed.
    """
    from playwright.sync_api import sync_playwright, Error as PlaywrightError

    vocab = [term for terms in signatures["consent_vocabulary"].values() for term in terms]
    overlay_args = {"vocab": vocab, "coverage": signatures["overlay_rule"]["min_viewport_coverage"]}
    dom_rule = signatures["login"]["dom_rule"]
    login_args = {"fold": dom_rule["above_the_fold_px"],
                  "maxChars": dom_rule["max_article_text_chars"]}

    def _run(active_browser):
        context = active_browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        try:
            response = page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)  # settle time for late JS
            text = page.evaluate("() => document.body ? document.body.innerText : ''")
            return {
                "ok": True,
                "status": response.status if response else None,
                "headers": dict(response.headers) if response else {},
                "final_url": page.url,
                "text": (text or "")[:TEXT_LIMIT],
                "consent_overlay": bool(page.evaluate(_OVERLAY_JS, overlay_args)),
                "login_dom": bool(page.evaluate(_LOGIN_JS, login_args)),
                "error": None,
            }
        finally:
            context.close()

    try:
        if browser is not None:
            return _run(browser)
        with sync_playwright() as pw:
            launched = pw.chromium.launch(headless=True)
            try:
                return _run(launched)
            finally:
                launched.close()
    except PlaywrightError as exc:
        return {"ok": False, "status": None, "headers": {}, "final_url": None,
                "text": "", "consent_overlay": False, "login_dom": False,
                "error": str(exc)[:500]}
    except Exception as exc:  # never let one site kill the shard
        return {"ok": False, "status": None, "headers": {}, "final_url": None,
                "text": "", "consent_overlay": False, "login_dom": False,
                "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
