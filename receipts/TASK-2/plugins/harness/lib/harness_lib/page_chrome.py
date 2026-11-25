"""Pieces every harness HTML page shares, read from the plugin's ``pages`` folder when a page renders.

``theme_script`` is the theme toggle (``pages/components/theme.js``) inlined in ``<head>``, so a stored
theme applies before the body draws. ``corner`` opens ``<body>``: the fixed upper-right block holding the
``operator-straps`` brand, a link to the marketplace's GitHub page, under which the toggle appends its
button at load.
"""
from __future__ import annotations

from harness_lib.project import plugin_root

PAGES = plugin_root() / "pages"
HOME = "https://github.com/t968rs/operator-straps"
BRAND = f'<a class="brand" href="{HOME}"><b>operator</b>-straps</a>'


def theme_script() -> str:
    """The theme toggle as an inline ``<script>`` element for ``<head>``."""
    return f"<script>\n{(PAGES / 'components' / 'theme.js').read_text(encoding='utf-8')}</script>"


def corner() -> str:
    """The fixed upper-right block: the brand, with the toggle's button appended under it at load."""
    return f'<div class="corner">{BRAND}</div>'
