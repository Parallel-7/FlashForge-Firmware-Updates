from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_index as bi  # noqa: E402
from mirror import REPO_ROOT  # noqa: E402

URL = "https://github.com/o/r/releases"


def _rel(tag, assets, published="2026-10-22T09:36:11Z", body=""):
    return {"tag_name": tag, "draft": False, "published_at": published, "body": body,
            "html_url": f"{URL}/tag/{tag}",
            "assets": [{"name": a, "browser_download_url": f"{URL}/download/{tag}/{a}"} for a in assets]}


RELEASES = [
    _rel("creator-5/1.9.10-1.2.9", ["raw-software-1.9.10.xz"]),
    _rel("creator-5/2.0.0-1.3.0", ["Creator5-2.0.0-1.3.0.tgz", "raw-kernel-2.0.7.xz", "raw-software-2.0.0.xz"]),
    _rel("creator-5/1.7.8-1.1.7", ["control-1.1.7.xz"], body="_Released by FlashForge on 2026-05-07; mirrored_"),
    _rel("v1.0", []),
]

README = f"# Title\n\nIntro.\n\n{bi.INDEX_START}\nold\n{bi.INDEX_END}\n\nFooter.\n"


def test_newest_version_first_and_latest_marked():
    page = bi.render(RELEASES, README)[REPO_ROOT / "printers" / "creator-5.md"]
    rows = [line for line in page.splitlines() if line.startswith("| ") and "Version" not in line]
    assert [r.split("|")[1].strip() for r in rows] == [
        "**2.0.0-1.3.0** (latest)", "1.9.10-1.2.9 ⚠️", "1.7.8-1.1.7 ⚠️"]
    assert "Creator5-2.0.0-1.3.0.tgz" in rows[0]
    assert "_not built yet_" in rows[1]
    assert "2026-05-07" in rows[2]  # FlashForge's date, not the mirror date
    assert "[!WARNING]" in page


def test_readme_keeps_hand_written_text():
    readme = bi.render(RELEASES, README)[REPO_ROOT / "README.md"]
    assert readme.startswith("# Title\n\nIntro.\n\n") and readme.endswith("\n\nFooter.\n")
    assert "| **Creator 5** | [2.0.0-1.3.0]" in readme
    assert "| Adventurer 5M | — |" in readme


def test_readme_needs_markers():
    with pytest.raises(ValueError):
        bi.render(RELEASES, "# no markers\n")
