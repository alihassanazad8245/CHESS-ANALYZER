"""Report exporters: ``json``, ``csv``, ``md`` and ``html``.

The HTML file is a self-contained static export - the analyzer itself stays
a CLI tool. Reports never contain any secret (there is none to leak here:
Chess.com's public API needs no key at all).
"""

from __future__ import annotations

import csv
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __app_name__, __version__
from .errors import AnalyzerError
from .models import PlayerReport

SUPPORTED_FORMATS = ("json", "csv", "md", "html")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_slug(value: str) -> str:
    """Turn a username into a filesystem-safe, traversal-proof stem."""
    slug = _SAFE_NAME.sub("-", value.replace("/", "-"))
    slug = re.sub(r"\.{2,}", ".", slug).strip("-.")
    return slug or "report"


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Flatten a nested report dict into ``key -> string`` pairs for CSV."""
    flat: dict[str, str] = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{name}."))
        elif isinstance(value, (list, tuple)):
            if value and isinstance(value[0], (dict, list, tuple)):
                flat[name] = json.dumps(value, ensure_ascii=False, default=str)
            else:
                flat[name] = ", ".join(str(item) for item in value)
        else:
            flat[name] = "" if value is None else str(value)
    return flat


def write_report(report: PlayerReport, fmt: str, output_dir: Path) -> Path:
    """Write ``report`` in ``fmt`` into ``output_dir`` and return the path."""
    fmt = fmt.lower().strip()
    if fmt not in SUPPORTED_FORMATS:
        raise AnalyzerError(
            f"Unsupported report format '{fmt}'.",
            hints=(f"Supported formats: {', '.join(SUPPORTED_FORMATS)}",),
        )

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AnalyzerError(
            f"Could not create the output directory '{output_dir}'.",
            hints=("Check the path and your write permissions",),
        ) from exc

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = output_dir / f"player-{safe_slug(report.username)}-{stamp}.{fmt}"

    try:
        {
            "json": _write_json, "csv": _write_csv, "md": _write_markdown, "html": _write_html,
        }[fmt](report, path)
    except OSError as exc:
        raise AnalyzerError(
            f"Could not write the report to '{path}'.",
            hints=("Check disk space and write permissions",),
        ) from exc

    return path


def _write_json(report: PlayerReport, path: Path) -> None:
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


def _write_csv(report: PlayerReport, path: Path) -> None:
    flat = _flatten(report.to_dict())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["field", "value"])
        for key, value in flat.items():
            writer.writerow([key, value])


def _markdown_lines(report: PlayerReport) -> list[str]:
    r = report
    lines = [
        f"# {__app_name__} report", "",
        f"**Player:** {r.username}{f' [{r.title}]' if r.title else ''}  ",
        f"**Generated:** {r.generated_at}  ",
        f"**Analyzer version:** {r.analyzer_version}", "",
        "## Profile", "",
        f"- Name: {r.name or 'N/A'}",
        f"- Country: {r.country_code}",
        f"- Profile: {r.profile_url}",
        f"- Joined: {r.joined} | Last online: {r.last_online}",
        f"- Followers: {r.followers:,}",
        "",
        "## Ratings by time class", "",
        "| Time class | Current | Best | W/L/D | Win rate |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {x.time_class.title()} | {x.current} | {x.best} | "
        f"{x.wins}/{x.losses}/{x.draws} | {x.win_rate}% |"
        for x in r.ratings
    ]
    lines += [
        "",
        "## Game results", "",
        f"- Games analysed: {r.games_analyzed} ({r.months_analyzed} months, {r.date_range})",
        f"- Record: {r.wins}W / {r.losses}L / {r.draws}D — {r.win_rate}% win rate",
        f"- As White: {r.white_games} games, {r.white_win_rate}% wins",
        f"- As Black: {r.black_games} games, {r.black_win_rate}% wins",
        "",
    ]
    if r.openings_as_white:
        lines += ["## Top openings as White", "", "| Opening | Games | Win rate |",
                  "| --- | --- | --- |"]
        lines += [f"| {o.name} | {o.games} | {o.win_rate}% |" for o in r.openings_as_white[:8]]
        lines.append("")
    if r.openings_as_black:
        lines += ["## Top openings as Black", "", "| Opening | Games | Win rate |",
                  "| --- | --- | --- |"]
        lines += [f"| {o.name} | {o.games} | {o.win_rate}% |" for o in r.openings_as_black[:8]]
        lines.append("")

    s = r.streaks
    lines += [
        "## Streaks and game length", "",
        f"- Longest win streak: {s.longest_win_streak}",
        f"- Longest loss streak: {s.longest_loss_streak}",
        f"- Average game length: {r.avg_game_length} moves",
        f"- Average accuracy: {r.avg_accuracy if r.avg_accuracy is not None else 'N/A'}%",
        "",
        "## Performance Index", "",
        "> This is an **Analyzer Metric** computed by this tool from public game data.",
        "> It is not an official Chess.com rating.",
        "",
        f"**{r.performance.total}/100 — {r.performance.grade}**", "",
        "| Dimension | Score |", "| --- | --- |",
    ]
    lines += [f"| {label} | {score}/{maximum} |" for label, score, maximum in r.performance.breakdown]
    lines.append("")
    if r.performance.notes:
        lines += ["### Observations", ""] + [f"- {n}" for n in r.performance.notes] + [""]
    if r.warnings:
        lines += ["## Notes", ""] + [f"- {w}" for w in r.warnings] + [""]
    lines.append(f"*Generated by {__app_name__} v{__version__}.*")
    return lines


def _write_markdown(report: PlayerReport, path: Path) -> None:
    path.write_text("\n".join(_markdown_lines(report)) + "\n", encoding="utf-8")


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light dark; --fg:#1b1f24; --bg:#ffffff; --muted:#5a6672;
  --accent:#2e7d32; --line:#d8dee4; --chip:#f2f5f8; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --fg:#e6edf3; --bg:#0d1117; --muted:#9198a1; --accent:#4caf50;
    --line:#30363d; --chip:#161b22; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:2rem 1rem; background:var(--bg); color:var(--fg);
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
main {{ max-width:940px; margin:0 auto; }}
h1 {{ font-size:1.8rem; border-bottom:2px solid var(--accent); padding-bottom:.5rem; }}
h2 {{ margin-top:2.2rem; font-size:1.25rem; border-bottom:1px solid var(--line); padding-bottom:.35rem; }}
table {{ border-collapse:collapse; width:100%; margin:1rem 0; font-size:.95rem;
  display:block; overflow-x:auto; }}
th,td {{ border:1px solid var(--line); padding:.5rem .75rem; text-align:left; }}
th {{ background:var(--chip); }}
tr:nth-child(even) td {{ background:color-mix(in srgb, var(--chip) 45%, transparent); }}
blockquote {{ margin:1rem 0; padding:.6rem 1rem; border-left:4px solid var(--accent);
  background:var(--chip); color:var(--muted); }}
footer {{ margin-top:3rem; color:var(--muted); font-size:.85rem;
  border-top:1px solid var(--line); padding-top:1rem; }}
ul {{ padding-left:1.2rem; }}
</style>
</head>
<body><main>
{body}
<footer>Static export generated by {app} v{version}. The Performance Index is produced by
this tool from public game data and is not an official Chess.com rating.</footer>
</main></body>
</html>
"""


def _markdown_to_html(lines: list[str]) -> str:
    out: list[str] = []
    in_table = in_list = header_done = False

    def inline(text: str) -> str:
        text = html.escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        return text

    def close_blocks() -> None:
        nonlocal in_table, in_list, header_done
        if in_table:
            out.append("</tbody></table>")
            in_table, header_done = False, False
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            close_blocks()
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if not in_table:
                out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells)
                            + "</tr></thead><tbody>")
                in_table = header_done = True
                continue
            out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue

        close_blocks()
        if line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
        else:
            out.append(f"<p>{inline(line)}</p>")

    close_blocks()
    return "\n".join(out)


def _write_html(report: PlayerReport, path: Path) -> None:
    body = _markdown_to_html(_markdown_lines(report))
    path.write_text(
        _HTML_TEMPLATE.format(
            title=html.escape(f"{__app_name__} — {report.username}"),
            body=body, app=html.escape(__app_name__), version=html.escape(__version__),
        ),
        encoding="utf-8",
    )
