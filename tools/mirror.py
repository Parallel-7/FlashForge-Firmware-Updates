"""Shared code for the mirror tools: printer models, release parsing, GitHub API.

Standard library only, so the tools run on a bare GitHub Actions runner.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
USB_KIT = REPO_ROOT / "usb-kit"
DEFAULT_REPO = "Parallel-7/FlashForge-Firmware-Updates"

PACKAGE_TYPES = ("kernel", "control", "library", "software")


@dataclass(frozen=True)
class Model:
    """One printer model and how its USB update works.

    The values come from each model's stock startup script (auto_run.sh or
    app_startup.sh) and stock USB update script.
    """

    slug: str  # release tag prefix, e.g. "creator-5"
    name: str  # display name, e.g. "Creator 5"
    machine: str  # MACHINE value; the USB file must be named <machine>-*.tgz
    pid: str
    arch: str  # `uname -m` on the printer
    run_dir: str  # where packages are installed
    script: str  # update script name the startup script runs
    install_order: tuple[str, ...]
    screens: str  # usb-kit/screens/<screens>/
    play: str  # usb-kit/play/<play>/
    family: str  # "5m", "ad5x" or "creator5": selects family-only steps


_5M_ORDER = ("control", "kernel", "software", "library")
_C5_ORDER = ("kernel", "control", "library", "software")

MODELS: dict[str, Model] = {
    m.slug: m
    for m in (
        Model("adventurer-5m", "Adventurer 5M", "Adventurer5M", "0023", "armv7l",
              "/opt/PROGRAM", "flashforge_init.sh", _5M_ORDER, "landscape", "arm", "5m"),
        Model("adventurer-5m-pro", "Adventurer 5M Pro", "Adventurer5MPro", "0024", "armv7l",
              "/opt/PROGRAM", "flashforge_init.sh", _5M_ORDER, "landscape", "arm", "5m"),
        Model("adventurer-5x", "Adventurer 5X (AD5X)", "AD5X", "0026", "mips",
              "/usr/prog/PROGRAM", "flashforge_init.sh", _5M_ORDER, "landscape", "mips", "ad5x"),
        Model("creator-5", "Creator 5", "Creator5", "0028", "mips",
              "/usr/prog/PROGRAM", "runFirmwareExe.sh", _C5_ORDER, "creator5", "mips", "creator5"),
        Model("creator-5-pro", "Creator 5 Pro", "Creator5Pro", "0029", "mips",
              "/usr/prog/PROGRAM", "runFirmwareExe.sh", _C5_ORDER, "creator5", "mips", "creator5"),
    )
}

# FlashForge: "After upgrading, this version cannot be rolled back to V1.9.8 or
# earlier versions via online or USB drive" (Creator 5 / 5 Pro kernel 2.0.7).
ROLLBACK_LIMITS: dict[str, tuple[int, ...]] = {
    "creator-5": (2, 0, 0),
    "creator-5-pro": (2, 0, 0),
}


def version_key(version: str) -> tuple:
    """Sort key for dotted versions ("1.9.10" > "1.9.8"). Non-numeric parts sort last."""
    parts = []
    for part in re.split(r"[.\-]", version):
        parts.append((0, int(part), "") if part.isdigit() else (1, 0, part))
    return tuple(parts)


@dataclass(frozen=True)
class Tag:
    slug: str
    software: str
    control: str

    @classmethod
    def parse(cls, tag: str) -> Tag | None:
        """Parse "<slug>/<software>-<control>". Return None for other tags."""
        m = re.fullmatch(r"([a-z0-9-]+)/([0-9][0-9.]*)-([0-9][0-9.]*)", tag)
        if not m or m.group(1) not in MODELS:
            return None
        return cls(m.group(1), m.group(2), m.group(3))

    @property
    def model(self) -> Model:
        return MODELS[self.slug]

    @property
    def usb_name(self) -> str:
        """The USB update file name. The printer matches /mnt/<machine>-*.tgz."""
        return f"{self.model.machine}-{self.software}-{self.control}.tgz"

    def sort_key(self) -> tuple:
        return (version_key(self.software), version_key(self.control))


def needs_rollback_warning(tag: Tag) -> bool:
    limit = ROLLBACK_LIMITS.get(tag.slug)
    return limit is not None and version_key(tag.software) < tuple((0, n, "") for n in limit)


_HEADING = re.compile(r"^###\s+(Kernel|Control|Library|Software)\s+([0-9][^\s]*)\s*$", re.M)
_ASSET = re.compile(r"^(?:raw-)?(kernel|control|library|software)-(.+)\.xz$")


def body_packages(body: str) -> dict[str, str]:
    """Package -> version from the release notes headings ("### Kernel 2.0.7")."""
    return {m.group(1).lower(): m.group(2) for m in _HEADING.finditer(body or "")}


def parse_asset_name(name: str) -> tuple[str, str] | None:
    """(package, version) for a raw OTA asset, old ("control-1.2.9.xz") or new
    ("raw-control-1.2.9.xz") name. None for anything else."""
    m = _ASSET.match(name)
    return (m.group(1), m.group(2)) if m else None


def raw_asset_name(package: str, version: str) -> str:
    return f"raw-{package}-{version}.xz"


# --------------------------------------------------------------------------
# GitHub API
# --------------------------------------------------------------------------


def github_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:  # local runs: reuse the gh CLI login
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


class GitHubError(RuntimeError):
    pass


class GitHub:
    """A small GitHub REST client for one repository."""

    API = "https://api.github.com"

    def __init__(self, repo: str | None = None, token: str | None = None):
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO
        self.token = token if token is not None else github_token()

    def _request(self, method: str, url: str, data: bytes | None = None,
                 headers: dict | None = None, timeout: float = 60) -> bytes:
        hdrs = {"Accept": "application/vnd.github+json", "User-Agent": "ff-firmware-mirror",
                "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        hdrs.update(headers or {})
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise GitHubError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc

    def api(self, method: str, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else None
        raw = self._request(method, f"{self.API}{path}", data, headers)
        return json.loads(raw) if raw else None

    def releases(self) -> list[dict]:
        """Every release (drafts included when the token can see them), newest first."""
        out: list[dict] = []
        page = 1
        while True:
            batch = self.api("GET", f"/repos/{self.repo}/releases?per_page=100&page={page}")
            out.extend(batch)
            if len(batch) < 100:
                return out
            page += 1

    def release_by_tag(self, tag: str) -> dict:
        return self.api("GET", f"/repos/{self.repo}/releases/tags/{urllib.parse.quote(tag, safe='')}")

    def update_release(self, release_id: int, **fields) -> dict:
        return self.api("PATCH", f"/repos/{self.repo}/releases/{release_id}", fields)

    def rename_asset(self, asset_id: int, name: str) -> dict:
        return self.api("PATCH", f"/repos/{self.repo}/releases/assets/{asset_id}", {"name": name})

    def delete_asset(self, asset_id: int) -> None:
        self.api("DELETE", f"/repos/{self.repo}/releases/assets/{asset_id}")

    def download(self, url: str) -> bytes:
        """Download a public browser_download_url (no auth header: it redirects to a CDN)."""
        req = urllib.request.Request(url, headers={"User-Agent": "ff-firmware-mirror"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            return resp.read()

    def upload_asset(self, release: dict, name: str, data: bytes,
                     content_type: str = "application/octet-stream") -> dict:
        base = release["upload_url"].split("{", 1)[0]
        url = f"{base}?{urllib.parse.urlencode({'name': name})}"
        raw = self._request("POST", url, data, {"Content-Type": content_type}, timeout=900)
        return json.loads(raw)
