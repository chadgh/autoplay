"""Render a simulation result to a standalone HTML report."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape


def render_report(result: dict) -> str:
    env = Environment(loader=PackageLoader("autoplay", "templates"), autoescape=select_autoescape(["html"]))
    # Escape "</" so card names can't close the <script> block.
    data_json = json.dumps(result).replace("</", "<\\/")
    return env.get_template("report.html").render(deck_name=result["deck"]["name"], data_json=_Safe(data_json))


def write_report(result: dict, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(render_report(result))
    return path


class _Safe(str):
    """Mark pre-escaped JSON as safe for Jinja autoescaping."""

    def __html__(self):
        return str(self)
