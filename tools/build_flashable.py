"""Build the USB update file for firmware releases and attach it to the release.

For each release tag "<slug>/<software>-<control>":

1. Rename old raw assets ("control-1.2.9.xz") to "raw-control-1.2.9.xz", so the
   USB file sorts first in the asset list.
2. Collect every package the release notes list. A package that the release
   does not have is taken from an earlier release of the same model that has
   the same version.
3. Write "<Machine>-<software>-<control>.tgz": a plain tar that holds the
   update script, the packages and the stock update screens. This is the
   format the printer's startup script reads from a USB drive.
4. Upload it and put a "USB update" section at the top of the release notes.

Usage:
    python tools/build_flashable.py --tag creator-5/2.0.0-1.3.0
    python tools/build_flashable.py --all
    python tools/build_flashable.py --tag creator-5/2.0.0-1.3.0 --dry-run --out build/
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mirror import (  # noqa: E402
    USB_KIT,
    GitHub,
    Model,
    Tag,
    body_packages,
    needs_rollback_warning,
    parse_asset_name,
    raw_asset_name,
)

USB_START = "<!-- usb-update:start -->"
USB_END = "<!-- usb-update:end -->"

# --------------------------------------------------------------------------
# Update script
# --------------------------------------------------------------------------

_5M_FUNCTIONS = """
# Make the RSA key pair if it is missing (as the stock 5M update script does).
create_key()
{
	key_dir=/opt/
	key_pair=${key_dir}private.pem
	public_key=${key_dir}key.pub
	private_key=${key_dir}key.priv
	password=abcd

	if [ ! -f ${key_pair} ];then
		export PATH=/opt/openssl-1.0.2d/bin:$PATH
		export OPENSSL_DIR=/opt/openssl-1.0.2d
		export LD_LIBRARY_PATH=$OPENSSL_DIR/lib:$LD_LIBRARY_PATH

		echo "CREATE RSA"
		openssl genrsa -des3 -passout pass:${password} -out ${key_pair} 2048
		openssl rsa -in ${key_pair} -passin pass:${password} -outform PEM -pubout -out ${public_key}
		openssl rsa -in ${key_pair} -passin pass:${password} -out ${private_key} -outform PEM
	fi
}
"""

_C5_FUNCTIONS = """
# Free space before the install, as the stock Creator 5 update scripts do.
# The removed folders are not used by Creator 5 firmware.
free_space()
{
	rm -f /usr/prog/PROGRAM/control/*.tar.xz*
	rm -f /usr/prog/PROGRAM/library/*.tar.xz*
	rm -f /usr/prog/PROGRAM/kernel/*.tar.xz*
	rm -f /usr/prog/PROGRAM/software/*.tar.xz*
	rm -rf /usr/prog/qt-4.8.6
	rm -rf /usr/prog/opencv-4.10
	rm -f /usr/prog/wifi/8821cu.ko*
	sync
}
"""

# The stock AD5X / Creator 5 scripts keep a copy of the update screen for later updates.
_KEEP_START_IMG = 'cp "${WORK_DIR}/start.img" /usr/prog/\nsync'

_FAMILY = {
    "5m": (_5M_FUNCTIONS, "create_key"),
    "ad5x": ("", _KEEP_START_IMG),
    "creator5": (_C5_FUNCTIONS, "free_space\n" + _KEEP_START_IMG),
}

# Stock behavior: run.sh runs for kernel, library and software. Control flashes
# the MCU on the next boot, from the startup script.
_RUN_SCRIPT = {"kernel": 1, "control": 0, "library": 1, "software": 1}


def render_script(model: Model) -> str:
    functions, steps = _FAMILY[model.family]
    install = "\n".join(f"install_pkg {p} {_RUN_SCRIPT[p]}" for p in model.install_order)
    # The printer runs this with sh: never let CRLF line endings in.
    text = (USB_KIT / "install.sh.in").read_text(encoding="utf-8").replace("\r\n", "\n")
    for key, value in {
        "@NAME@": model.name, "@MACHINE@": model.machine, "@PID@": model.pid,
        "@ARCH@": model.arch, "@RUN_DIR@": model.run_dir, "@SCRIPT@": model.script,
        "@FAMILY_FUNCTIONS@": functions, "@FAMILY_STEPS@": steps,
        "@INSTALL_STEPS@": install,
    }.items():
        text = text.replace(key, value)
    return text


# --------------------------------------------------------------------------
# Archive
# --------------------------------------------------------------------------


def check_package(name: str, data: bytes) -> None:
    """Fail if a raw package is not a tar with an md5sum.list (the printer needs one)."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
            names = {m.name.lstrip("./") for m in tar.getmembers()}
    except tarfile.TarError as exc:
        raise ValueError(f"{name} is not a plain tar archive: {exc}") from exc
    if "md5sum.list" not in names:
        raise ValueError(f"{name} has no md5sum.list")


def build_archive(model: Model, packages: dict[str, tuple[str, bytes]], mtime: int) -> bytes:
    """Return the plain-tar USB file.

    ``packages`` maps package -> (version, raw bytes). Members use "./" paths and
    root ownership, like FlashForge's own USB files. Scripts are 0755.
    """
    files: list[tuple[str, bytes, int]] = [(model.script, render_script(model).encode(), 0o755)]
    pkg_files = [(f"{p}-{packages[p][0]}.tar.xz", packages[p][1])
                 for p in model.install_order if p in packages]
    md5_lines = "".join(f"{hashlib.md5(d).hexdigest()}  {n}\n" for n, d in pkg_files)
    files.append(("packages.md5", md5_lines.encode(), 0o644))
    files.extend((n, d, 0o644) for n, d in pkg_files)
    screens = USB_KIT / "screens" / model.screens
    files.append(("start.img", (screens / "start.img").read_bytes(), 0o644))
    files.append(("end.img", (screens / "end.img").read_bytes(), 0o644))
    files.append(("play", (USB_KIT / "play" / model.play / "play").read_bytes(), 0o755))

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:", format=tarfile.GNU_FORMAT) as tar:
        for name, data, mode in files:
            info = tarfile.TarInfo(f"./{name}")
            info.size = len(data)
            info.mode = mode
            info.mtime = mtime
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# --------------------------------------------------------------------------
# Package selection
# --------------------------------------------------------------------------


@dataclass
class Plan:
    tag: Tag
    release: dict
    # package -> (version, asset dict, tag the asset belongs to)
    sources: dict[str, tuple[str, dict, str]] = field(default_factory=dict)
    missing: dict[str, str] = field(default_factory=dict)  # package -> version


def asset_index(releases: list[dict]) -> dict[tuple[str, str, str], tuple[dict, str]]:
    """(slug, package, version) -> (asset, tag), first match in the order given."""
    index: dict[tuple[str, str, str], tuple[dict, str]] = {}
    for rel in releases:
        tag = Tag.parse(rel.get("tag_name", ""))
        if tag is None or rel.get("draft"):
            continue
        for asset in rel.get("assets", []):
            parsed = parse_asset_name(asset["name"])
            if parsed:
                index.setdefault((tag.slug, *parsed), (asset, rel["tag_name"]))
    return index


def plan_release(release: dict, all_releases: list[dict]) -> Plan:
    tag = Tag.parse(release["tag_name"])
    if tag is None:
        raise ValueError(f"not a firmware release tag: {release['tag_name']}")
    own = asset_index([release])
    others = asset_index(all_releases)
    wanted = body_packages(release.get("body", ""))
    for (_, pkg, ver) in own:  # assets the notes do not list still count
        wanted.setdefault(pkg, ver)
    plan = Plan(tag, release)
    for pkg, ver in wanted.items():
        hit = own.get((tag.slug, pkg, ver)) or others.get((tag.slug, pkg, ver))
        if hit:
            plan.sources[pkg] = (ver, hit[0], hit[1])
        else:
            plan.missing[pkg] = ver
    for required in ("software",):
        if required not in plan.sources:
            raise ValueError(f"{tag.slug} {tag.software}: no {required} package available")
    return plan


# --------------------------------------------------------------------------
# Release notes
# --------------------------------------------------------------------------


def usb_section(plan: Plan, usb_url: str) -> str:
    tag = plan.tag
    name = tag.usb_name
    lines = [
        USB_START,
        "## USB update",
        "",
        f"**Download: [{name}]({usb_url})**",
        "",
        "1. Format a USB drive as FAT32.",
        "2. Copy the file to the root of the drive. Do not rename or extract it.",
        f"   Keep only one `{tag.model.machine}-*.tgz` file on the drive.",
        "3. Turn off the printer and insert the USB drive.",
        "4. Turn on the printer. The update starts automatically.",
        "5. Wait for the \"Upgrade completed\" screen. Remove the USB drive and restart the printer.",
        "",
    ]
    if needs_rollback_warning(tag):
        lines += [
            "> [!WARNING]",
            f"> Do not install this version on a {tag.model.name} that has firmware 2.0.0 or later.",
            "> FlashForge states that 2.0.0 cannot be rolled back to 1.9.8 or earlier.",
            "> A rollback can cause errors.",
            "",
        ]
    contents = ", ".join(f"{p} {plan.sources[p][0]}" for p in tag.model.install_order
                         if p in plan.sources)
    lines.append(f"Packages in this file: {contents}.")
    borrowed = [p for p in tag.model.install_order
                if p in plan.sources and plan.sources[p][2] != plan.release["tag_name"]]
    if borrowed:
        lines.append("Packages that did not change in this release come from the earlier "
                     "release with the same version.")
    if plan.missing:
        miss = ", ".join(f"{p} {v}" for p, v in plan.missing.items())
        lines.append(f"Not in this file (not available from the update server): {miss}.")
    lines += [
        "",
        "The `raw-*.xz` files are the original packages from the FlashForge update server "
        "(plain tar). Use them for development. Use the `.tgz` file to update a printer.",
        USB_END,
        "",
    ]
    return "\n".join(lines)


def with_usb_section(body: str, section: str) -> str:
    body = body or ""
    if USB_START in body and USB_END in body:
        before, rest = body.split(USB_START, 1)
        after = rest.split(USB_END, 1)[1]
        return before + section.rstrip("\n") + after
    return section + "\n" + body.lstrip("\n")


# --------------------------------------------------------------------------
# Main flow
# --------------------------------------------------------------------------


def rename_raw_assets(gh: GitHub, release: dict, dry_run: bool) -> None:
    names = {a["name"] for a in release.get("assets", [])}
    for asset in release.get("assets", []):
        parsed = parse_asset_name(asset["name"])
        if not parsed or asset["name"].startswith("raw-"):
            continue
        new = raw_asset_name(*parsed)
        if new in names:
            continue
        print(f"  rename {asset['name']} -> {new}")
        if not dry_run:
            updated = gh.rename_asset(asset["id"], new)
            asset.update(name=updated["name"], browser_download_url=updated["browser_download_url"])


def process(gh: GitHub, release: dict, all_releases: list[dict], *, force: bool,
            dry_run: bool, out_dir: Path | None) -> str:
    tag = Tag.parse(release["tag_name"])
    print(f"{release['tag_name']}:")
    rename_raw_assets(gh, release, dry_run)
    plan = plan_release(release, all_releases)
    existing = next((a for a in release.get("assets", []) if a["name"] == tag.usb_name), None)
    usb_url = (f"https://github.com/{gh.repo}/releases/download/"
               f"{release['tag_name']}/{tag.usb_name}")

    if existing and not force and not out_dir:
        print(f"  {tag.usb_name} exists")
    else:
        packages: dict[str, tuple[str, bytes]] = {}
        for pkg, (ver, asset, from_tag) in plan.sources.items():
            note = "" if from_tag == release["tag_name"] else f" (from {from_tag})"
            print(f"  get {asset['name']}{note}")
            data = gh.download(asset["browser_download_url"])
            if asset.get("size") is not None and len(data) != asset["size"]:
                raise ValueError(f"{asset['name']}: size {len(data)} != {asset['size']}")
            check_package(asset["name"], data)
            packages[pkg] = (ver, data)
        published = release.get("published_at") or release.get("created_at")
        mtime = int(datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp())
        archive = build_archive(tag.model, packages, mtime)
        print(f"  built {tag.usb_name} ({len(archive) / 1e6:.1f} MB)")
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / tag.usb_name).write_bytes(archive)
        if not dry_run:
            if existing:
                gh.delete_asset(existing["id"])
            gh.upload_asset(release, tag.usb_name, archive)
            print("  uploaded")

    body = with_usb_section(release.get("body", ""), usb_section(plan, usb_url))
    if body != (release.get("body") or ""):
        print("  update release notes")
        if not dry_run:
            gh.update_release(release["id"], body=body)
    return tag.usb_name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", action="append", default=[], help="release tag (repeatable)")
    ap.add_argument("--all", action="store_true", help="every firmware release")
    ap.add_argument("--force", action="store_true", help="rebuild a USB file that exists")
    ap.add_argument("--dry-run", action="store_true", help="change nothing on GitHub")
    ap.add_argument("--out", type=Path, help="also write the USB files to this folder")
    ap.add_argument("--repo", help="owner/name (default: $GITHUB_REPOSITORY or the mirror)")
    args = ap.parse_args(argv)
    if not args.tag and not args.all:
        ap.error("give --tag or --all")

    gh = GitHub(args.repo)
    releases = [r for r in gh.releases() if not r.get("draft")]
    if args.all:
        targets = [r for r in releases if Tag.parse(r["tag_name"])]
    else:
        by_tag = {r["tag_name"]: r for r in releases}
        missing = [t for t in args.tag if t not in by_tag]
        if missing:
            ap.error(f"no published release for: {', '.join(missing)}")
        targets = [by_tag[t] for t in args.tag]

    failures = 0
    for rel in targets:
        if Tag.parse(rel["tag_name"]) is None:
            print(f"{rel['tag_name']}: not a firmware release, skip")
            continue
        try:
            process(gh, rel, releases, force=args.force, dry_run=args.dry_run, out_dir=args.out)
        except Exception as exc:  # keep going; report at the end
            failures += 1
            print(f"  FAILED: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
