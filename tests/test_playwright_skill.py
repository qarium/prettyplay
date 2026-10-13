"""Empirical verification of the packaged Playwright skill: every example runs green."""

import http.server
import json
import re
import threading
from pathlib import Path
from urllib.parse import unquote

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright
from prettyplay.skills import load_skill

SKILL_FILE = Path(__file__).resolve().parents[1] / "prettyplay" / "skills" / "playwright" / "SKILL.md"
ENGINE_CODEMANIFEST = Path(__file__).resolve().parents[1] / "prettyplay" / "engine" / "CODEMANIFEST"

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Shop</title>
<style>
  #menu .menu-item { display: none; }
  #menu:hover .menu-item, #menu.open .menu-item { display: block; }
  #feed { height: 150px; overflow-y: scroll; }
  #bottom { margin-top: 2000px; }
</style>
</head>
<body>
  <div id="modal">
    <button id="close-modal" type="button"
        onclick="document.getElementById('modal').remove()">Close</button>
  </div>
  <div id="settings">
    <button id="save-changes" type="button">Save changes</button>
  </div>
  <div id="auth">
    <button id="signin" type="button">Sign in</button>
  </div>
  <span id="newsletter-opt-in"></span>
  <main id="main">
    <h1>Latest announcements</h1>
    <form id="search-form" onsubmit="event.preventDefault();
            document.getElementById('result').textContent =
                'submitted: ' + document.getElementById('search').value;">
      <input id="search" name="q" placeholder="Search" aria-label="Search" role="textbox">
    </form>
    <p id="result" role="status"></p>
    <ul id="results">
      <li>Release notes 2.4</li>
      <li>Announcements archive</li>
      <li>Change log index</li>
      <li>Unrelated entry</li>
      <li>Another unrelated entry</li>
    </ul>
    <a id="account-link" href="account.html?id=7">Open the account</a>
    <a id="new-tab" href="profile.html" target="_blank">Open the profile</a>

    <select id="color" onchange="document.getElementById('color-result').textContent = this.value">
      <option value="red">Red</option>
      <option value="blue">Blue</option>
    </select>
    <p id="color-result"></p>

    <input type="checkbox" id="check">
    <label><input type="radio" name="size" value="large"
        onchange="document.getElementById('size-result').textContent = this.value"> Large</label>
    <p id="size-result"></p>

    <textarea id="notes"></textarea>
    <input type="file" id="upload"
        onchange="setTimeout(async () => {
          await fetch('/api/uploads', {method: 'POST', body: this.files[0].name});
          document.getElementById('upload-result').textContent = 'uploaded: ' + this.files[0].name;
        }, 200)">
    <p id="upload-result"></p>

    <button id="slow-btn" type="button"
        onclick="setTimeout(() => document.getElementById('slow-result').textContent = 'done', 300)">Slow</button>
    <p id="slow-result"></p>
    <button id="remove-btn" type="button" onclick="victim.remove()">Remove</button>
    <p id="victim">vanishing</p>

    <table id="orders"><tbody>
      <tr data-id="a-100"><td>alpha</td></tr>
      <tr data-id="b-200"><td>beta</td></tr>
      <tr data-id="c-300"><td>gamma</td></tr>
      <tr data-id="d-400"><td>delta</td></tr>
    </tbody></table>

    <iframe id="frame" title="widget" srcdoc="
        <button id='frame-btn' type='button'
          onclick=&quot;parent.document.getElementById('frame-result').textContent = 'clicked'&quot;>
          Frame action</button>"></iframe>
    <p id="frame-result"></p>

    <my-card></my-card>
    <p id="shadow-result"></p>

    <div id="menu">Menu
      <div class="menu-item">
        <button id="menu-open" type="button"
            onclick="document.getElementById('menu-result').textContent = 'opened'">Open</button>
      </div>
    </div>
    <p id="menu-result"></p>

    <button id="alert-btn" type="button" onclick="alert('hi')">Alert</button>
    <button id="dbl-btn" type="button"
        ondblclick="document.getElementById('dbl-result').textContent = 'double'">Double</button>
    <p id="dbl-result"></p>

    <div id="drag-src" draggable="true">Drag me</div>
    <div id="drop-zone">Drop here</div>
    <p id="drop-result"></p>

    <button id="enable-search" type="button"
        onclick="const box = document.getElementById('lazy-box');
                 box.disabled = false; box.classList.add('is-active')">Advanced search</button>
    <input id="lazy-box" disabled>

    <div id="dialog">
      <h2 id="modal-title">Confirm the order</h2>
      <input id="modal-field" readonly>
    </div>

    <div id="spinner">Loading</div>

    <button id="checkout" type="button" disabled>Checkout</button>

    <button id="next-page" type="button"
        onclick="setTimeout(() => {
          document.querySelector('#orders tbody').innerHTML =
            '<tr data-id=&quot;e-500&quot;><td>epsilon</td></tr><tr data-id=&quot;f-600&quot;><td>zeta</td></tr>';
        }, 150)">Next page</button>

    <input id="live-box" aria-label="Filter">
    <p id="live-result"></p>

    <div id="feed"></div>

    <button id="fetch-btn" type="button" onclick="fetchQuote()">Load quote</button>
    <p id="fetch-result"></p>
    <button id="order-btn" type="button" onclick="placeOrder()">Place order</button>
    <p id="order-result"></p>

    <p id="bottom">bottom</p>
  </main>
  <script>
    class MyCard extends HTMLElement {
      constructor() {
        super();
        const root = this.attachShadow({mode: 'open'});
        root.innerHTML = '<button id="shadow-btn" type="button">Shadow action</button>';
        root.getElementById('shadow-btn').addEventListener('click', () => {
          document.getElementById('shadow-result').textContent = 'shadow done';
        });
      }
    }
    customElements.define('my-card', MyCard);

    setTimeout(() => {
      document.getElementById('spinner').remove();
      const checkout = document.getElementById('checkout');
      checkout.disabled = false;
      document.body.classList.add('is-hydrated');
    }, 200);

    document.getElementById('modal-title').addEventListener('click', () => {
      document.getElementById('modal-field').readOnly = false;
    });

    let liveTimer = null;
    const liveBox = document.getElementById('live-box');
    function liveSearch() {
      fetch('/api/search?q=' + encodeURIComponent(liveBox.value))
        .then(r => r.json())
        .then(data => document.getElementById('live-result').textContent = 'for: ' + data.query);
    }
    liveBox.addEventListener('input', () => {
      clearTimeout(liveTimer);
      liveTimer = setTimeout(liveSearch, 250);
    });
    liveBox.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') liveSearch();
    });

    const feed = document.getElementById('feed');
    let feedBatch = 0;
    function appendFeedBatch() {
      feedBatch += 1;
      for (let i = 0; i < 10; i += 1) {
        const entry = document.createElement('p');
        entry.textContent = feedBatch === 4 && i === 9 ? 'final entry' : 'feed entry ' + feedBatch + '-' + i;
        feed.appendChild(entry);
      }
    }
    appendFeedBatch();
    feed.addEventListener('wheel', () => {
      if (feedBatch < 6) appendFeedBatch();
    });

    async function fetchQuote() {
      const response = await fetch('/api/quote');
      const data = await response.json();
      document.getElementById('fetch-result').textContent = 'price: ' + data.price;
    }
    async function placeOrder() {
      const response = await fetch('/api/orders', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({item: 'winter tires'}),
      });
      const data = await response.json();
      document.getElementById('order-result').textContent = 'order ' + data.id;
    }

    const src = document.getElementById('drag-src');
    const zone = document.getElementById('drop-zone');
    src.addEventListener('dragstart', (event) => event.dataTransfer.setData('text/plain', 'x'));
    zone.addEventListener('dragover', (event) => event.preventDefault());
    zone.addEventListener('drop', (event) => {
      event.preventDefault();
      document.getElementById('drop-result').textContent = 'dropped';
    });
  </script>
</body>
</html>
"""

ACCOUNT_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Account</title></head>
<body><h1>Latest announcements</h1></body>
</html>
"""

PROFILE_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Profile</title></head>
<body><h1>Latest announcements</h1></body>
</html>
"""

_FENCED_PYTHON = re.compile(r"```python\n(.*?)```", re.DOTALL)


def _skill_blocks() -> list[str]:
    """Extract every fenced python block of the packaged skill."""
    return _FENCED_PYTHON.findall(SKILL_FILE.read_text(encoding="utf-8"))


class TestPlaywrightSkillContract:
    """Contract tests: the packaged file, the loader and the manifest connection agree."""

    def test_the_loader_reads_the_packaged_file(self) -> None:
        assert load_skill("playwright") == SKILL_FILE.read_text(encoding="utf-8")
        assert "strict mode" in load_skill("playwright")  # non-empty readable content

    def test_a_missing_skill_name_raises_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_skill("no-such-skill")

    def test_the_manifest_usage_documents_the_connection(self) -> None:
        """The imported usage explains how to connect the skill — it never restates the content."""
        text = ENGINE_CODEMANIFEST.read_text(encoding="utf-8")
        assert "load_skill" in text  # the manifest names the facade function
        assert "prettyplay/skills" in text  # it names the skills cell
        import_segment = text[text.index("- load_skill") : text.index("From: prettyplay/skills")]
        assert "Usages:" in import_segment  # the practice rides the import
        assert "- playwright" in import_segment
        usage = (SKILL_FILE.parent.parent / ".usages" / "playwright.md").read_text(encoding="utf-8")
        assert "load_skill" in usage  # the practice names the facade function
        skill = SKILL_FILE.read_text(encoding="utf-8")
        # the practice must be far shorter than the skill itself — a connection note, not a copy
        assert len(usage) < len(skill) / 3

    def test_the_skill_is_a_pattern_library(self) -> None:
        blocks = _skill_blocks()
        assert len(blocks) >= 40  # every section ships runnable patterns, not a token sheet


class TestPlaywrightSkillExamples:
    """Empirical tests: every fenced example executes green against the local fixture page."""

    def test_every_example_runs_green_on_the_fixture_page(self, tmp_path: Path) -> None:  # noqa: C901 — one section per skill block, the walk mirrors the skill's own structure
        (tmp_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
        (tmp_path / "account.html").write_text(ACCOUNT_HTML, encoding="utf-8")
        (tmp_path / "profile.html").write_text(PROFILE_HTML, encoding="utf-8")

        class _Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, directory=str(tmp_path), **kwargs)

            def do_GET(self) -> None:
                if self.path.startswith("/api/search"):
                    query = unquote(self.path.partition("q=")[2])
                    body = json.dumps({"query": query, "results": ["match"]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/api/quote":
                    body = json.dumps({"price": 42}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                super().do_GET()

            def do_POST(self) -> None:
                if self.path == "/api/uploads":
                    length = int(self.headers.get("Content-Length", 0))
                    self.rfile.read(length)
                    body = json.dumps({"ok": True}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/api/orders":
                    length = int(self.headers.get("Content-Length", 0))
                    self.rfile.read(length)
                    body = json.dumps({"status": "created", "id": 7}).encode()
                    self.send_response(201)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        index_url = f"http://127.0.0.1:{server.server_port}/index.html"

        blocks = _skill_blocks()
        assert blocks, "no fenced python blocks found in the skill"

        try:
            playwright = sync_playwright().start()
        except PlaywrightError:
            pytest.skip("playwright is not available")
        try:
            try:
                browser = playwright.chromium.launch(headless=True)
            except PlaywrightError:
                browser = playwright.chromium.launch(channel="chrome", headless=True)  # the system Chrome
        except PlaywrightError:
            pytest.skip("no playwright browser is installed (chromium bundle or system chrome)")
        else:
            try:
                page = browser.new_page()
                for block in blocks:
                    page.goto(index_url)  # a fresh page state per example — no cross-block leakage
                    namespace = {"page": page, "expect": expect, "re": re}
                    exec(block, namespace)
                page.close()
            finally:
                browser.close()
        finally:
            playwright.stop()
            server.shutdown()
