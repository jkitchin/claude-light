"""The GitHub Pages site in docs/ uses copies of the server's static files.
Copy them again when the server's change:

    cp claude/static/{style.css,app.js,stats.js} docs/
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('name', ['style.css', 'app.js', 'stats.js'])
def test_docs_assets_match_server(name):
    assert ((ROOT / 'docs' / name).read_text()
            == (ROOT / 'claude' / 'static' / name).read_text())


def test_docs_pages_use_live_api():
    for page in (ROOT / 'docs').glob('*.html'):
        text = page.read_text()
        assert "window.CLAUDE_LIGHT_API = 'https://claude-light.cheme.cmu.edu'" in text, page.name
