"""Tests for the USB update builder.

The sandbox tests run the generated update script with `sh` against a fake
printer file system: absolute printer paths are moved under a temp folder and
`uname` is replaced by a stub. Set FF_TEST_SHELLS (e.g. "sh busybox-sh") to
choose shells; "busybox-sh" means `busybox sh`.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_flashable as bf  # noqa: E402
from mirror import MODELS, Tag, body_packages, needs_rollback_warning, parse_asset_name  # noqa: E402

# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_parse_tag_and_usb_name():
    tag = Tag.parse("creator-5-pro/2.0.0-1.3.0")
    assert tag and tag.slug == "creator-5-pro" and tag.software == "2.0.0" and tag.control == "1.3.0"
    assert tag.usb_name == "Creator5Pro-2.0.0-1.3.0.tgz"
    assert Tag.parse("v1.0.0") is None
    assert Tag.parse("unknown-printer/1.0.0-1.0.0") is None


def test_usb_name_sorts_before_raw_assets():
    # GitHub lists assets by name, ignoring case. The USB file must come first.
    for slug in MODELS:
        tag = Tag.parse(f"{slug}/1.0.0-1.0.0")
        names = [tag.usb_name, "raw-control-1.0.0.xz", "raw-kernel-1.0.0.xz",
                 "raw-library-1.0.0.xz", "raw-software-1.0.0.xz"]
        assert sorted(names, key=str.lower)[0] == tag.usb_name


def test_parse_asset_names():
    assert parse_asset_name("control-1.2.9.xz") == ("control", "1.2.9")
    assert parse_asset_name("raw-software-2.0.0.xz") == ("software", "2.0.0")
    assert parse_asset_name("Creator5-2.0.0-1.3.0.tgz") is None


def test_body_packages():
    body = "## X\n\n### Kernel 2.0.7\n- a\n\n### Control 1.3.0\n_(none)_\n### Software 2.0.0\n"
    assert body_packages(body) == {"kernel": "2.0.7", "control": "1.3.0", "software": "2.0.0"}


def test_rollback_warning():
    assert needs_rollback_warning(Tag.parse("creator-5/1.9.8-1.2.9"))
    assert needs_rollback_warning(Tag.parse("creator-5-pro/1.7.8-1.1.7"))
    assert not needs_rollback_warning(Tag.parse("creator-5/2.0.0-1.3.0"))
    assert not needs_rollback_warning(Tag.parse("adventurer-5m/5.1.9-2.2.3"))


# --------------------------------------------------------------------------
# Package selection and release notes
# --------------------------------------------------------------------------


def _asset(name, size=10):
    return {"name": name, "size": size, "id": hash(name) & 0xFFFF,
            "browser_download_url": f"https://example.invalid/{name}"}


def _release(tag, body, assets):
    return {"tag_name": tag, "body": body, "assets": [_asset(a) for a in assets], "id": 1,
            "draft": False, "published_at": "2026-10-22T09:36:11Z"}


def test_plan_borrows_unchanged_packages_and_reports_missing():
    old = _release("adventurer-5m/5.1.8-2.2.3", "",
                   ["control-2.2.3.xz", "library-2.5.0.xz", "software-5.1.8.xz"])
    new = _release("adventurer-5m/5.1.9-2.2.3",
                   "### Kernel 2.1.6\n### Control 2.2.3\n### Library 2.5.0\n### Software 5.1.9\n",
                   ["software-5.1.9.xz"])
    plan = bf.plan_release(new, [new, old])
    assert plan.sources["software"][2] == "adventurer-5m/5.1.9-2.2.3"
    assert plan.sources["control"][2] == "adventurer-5m/5.1.8-2.2.3"
    assert plan.sources["library"][1]["name"] == "library-2.5.0.xz"
    assert plan.missing == {"kernel": "2.1.6"}


def test_plan_never_borrows_from_another_model():
    other = _release("adventurer-5m-pro/5.1.8-2.2.3", "", ["control-2.2.3.xz"])
    new = _release("adventurer-5m/5.1.9-2.2.3", "### Control 2.2.3\n### Software 5.1.9\n",
                   ["software-5.1.9.xz"])
    assert bf.plan_release(new, [new, other]).missing == {"control": "2.2.3"}


def test_usb_section_is_idempotent_and_warns_on_rollback():
    rel = _release("creator-5/1.9.8-1.2.9", "## Creator 5 1.9.8 Update\n\n### Software 1.9.8\n",
                   ["software-1.9.8.xz"])
    plan = bf.plan_release(rel, [rel])
    section = bf.usb_section(plan, "https://example.invalid/Creator5-1.9.8-1.2.9.tgz")
    assert "[!WARNING]" in section and "Creator5-1.9.8-1.2.9.tgz" in section
    once = bf.with_usb_section(rel["body"], section)
    assert once.startswith(bf.USB_START) and once.endswith(rel["body"])
    assert bf.with_usb_section(once, section) == once


# --------------------------------------------------------------------------
# Archive layout
# --------------------------------------------------------------------------


def _fake_package(pkg: str, version: str, root: Path, bad_md5: bool = False) -> bytes:
    """A package like FlashForge's: md5sum.list + run.sh + payload, plain tar."""
    run_sh = f'#!/bin/sh\necho "{pkg} {version}" > "{root.as_posix()}/ran-{pkg}"\n'.encode()
    payload = f"{pkg} payload {version}\n".encode()
    files = {"run.sh": run_sh, "payload.bin": payload}
    lines = "".join(f"{hashlib.md5(d).hexdigest()}  ./{n}\n" for n, d in files.items())
    if bad_md5:
        lines = lines.replace(hashlib.md5(payload).hexdigest(), "0" * 32)
    files["md5sum.list"] = lines.encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(f"./{name}")
            info.size, info.mode = len(data), 0o755
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_archive_layout_matches_stock_usb_files(tmp_path):
    model = MODELS["creator-5"]
    pkgs = {p: ("1.0", _fake_package(p, "1.0", tmp_path)) for p in ("software", "kernel")}
    data = bf.build_archive(model, pkgs, mtime=0)
    assert data[:2] == b"./"  # plain tar, not gzip: the stock startup scripts run `tar -xvf`
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members = {m.name: m for m in tar.getmembers()}
    assert list(members) == ["./runFirmwareExe.sh", "./packages.md5", "./kernel-1.0.tar.xz",
                             "./software-1.0.tar.xz", "./start.img", "./end.img", "./play"]
    assert members["./runFirmwareExe.sh"].mode == 0o755 and members["./play"].mode == 0o755
    assert all(m.uid == 0 and m.gid == 0 for m in members.values())


def test_check_package_rejects_non_tar():
    with pytest.raises(ValueError):
        bf.check_package("x.xz", b"not a tar file" * 100)


# --------------------------------------------------------------------------
# Sandbox: run the generated script
# --------------------------------------------------------------------------


def _shells() -> list[list[str]]:
    wanted = os.environ.get("FF_TEST_SHELLS", "sh").split()
    shells = []
    for name in wanted:
        cmd = ["busybox", "sh"] if name == "busybox-sh" else [name]
        if shutil.which(cmd[0]):
            shells.append(cmd)
    return shells or [["sh"]]


SHELLS = _shells()


def _install(tmp_path: Path, slug: str, *, args=None, arch=None, corrupt=False,
             bad_inner=None, shell=None):
    """Build a USB file with fake packages, unpack it like the printer does and run it."""
    model = MODELS[slug]
    root = tmp_path / "root"
    root.mkdir()
    versions = {p: f"9.{i}" for i, p in enumerate(model.install_order)}
    pkgs = {p: (v, _fake_package(p, v, root, bad_md5=(p == bad_inner))) for p, v in versions.items()}
    archive = bf.build_archive(model, pkgs, mtime=0)

    update = root / "data" / "update"
    update.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(update, filter="fully_trusted")
    if corrupt:
        victim = update / f"software-{versions['software']}.tar.xz"
        victim.write_bytes(victim.read_bytes()[:-1] + b"X")

    # Move printer paths under the sandbox root.
    script = update / model.script
    text = script.read_text()
    for path in ("/usr/prog", "/opt/", "/dev/fb0"):
        text = text.replace(path, f"{root.as_posix()}{path}")
    # Call the uname stub by path: static busybox prefers its own applet over PATH.
    stub = tmp_path / "bin"
    text = text.replace("`uname -m`", f"`{stub.as_posix()}/uname -m`")
    script.write_text(text, newline="\n")

    # An old installed version, a folder free_space must delete, an existing key.
    (root / model.run_dir.lstrip("/") / "software" / "0.1").mkdir(parents=True)
    (root / "usr/prog/qt-4.8.6").mkdir(parents=True)
    (root / "opt").mkdir(exist_ok=True)
    (root / "opt/private.pem").write_text("keep")
    (root / "dev").mkdir()

    stub.mkdir()
    (stub / "uname").write_text(f"#!/bin/sh\necho {arch or model.arch}\n", newline="\n")
    (stub / "uname").chmod(0o755)
    cmd = (shell or SHELLS[0]) + [script.as_posix()]
    cmd += [model.machine, model.pid] if args is None else args
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=60)
    return proc, root, versions, model


@pytest.mark.parametrize("shell", SHELLS, ids=lambda s: " ".join(s))
@pytest.mark.parametrize("slug", sorted(MODELS))
def test_install_all_packages(tmp_path, slug, shell):
    proc, root, versions, model = _install(tmp_path, slug, shell=shell)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    run_dir = root / model.run_dir.lstrip("/")
    for pkg, ver in versions.items():
        assert (run_dir / pkg / ver / "payload.bin").is_file(), pkg
        assert sorted(p.name for p in (run_dir / pkg).iterdir()) == [ver]
    # Stock: run.sh runs for kernel, library and software, never for control.
    assert {p.name for p in root.glob("ran-*")} == {"ran-kernel", "ran-library", "ran-software"}
    assert (root / "dev/fb0").read_bytes() == (bf.USB_KIT / "screens" / model.screens / "end.img").read_bytes()
    assert (root / "opt/private.pem").read_text() == "keep"
    assert (root / "usr/prog/qt-4.8.6").exists() == (model.family != "creator5")


def test_install_without_arguments(tmp_path):
    proc, root, versions, model = _install(tmp_path, "adventurer-5x", args=[])
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("kwargs", [
    {"args": ["Adventurer5M", "0023"]},  # an AD5X file on a 5M
    {"arch": "x86_64"},
    {"corrupt": True},
], ids=["wrong-model", "wrong-arch", "corrupt-file"])
def test_install_refuses_and_changes_nothing(tmp_path, kwargs):
    proc, root, versions, model = _install(tmp_path, "adventurer-5x", **kwargs)
    assert proc.returncode == 1
    run_dir = root / model.run_dir.lstrip("/")
    assert [p.name for p in (run_dir / "software").iterdir()] == ["0.1"]
    assert not list(root.glob("ran-*"))


def test_install_reports_bad_package(tmp_path):
    proc, root, versions, model = _install(tmp_path, "creator-5", bad_inner="library")
    assert proc.returncode == 1  # no "Upgrade completed" screen
    run_dir = root / model.run_dir.lstrip("/")
    assert not (run_dir / "library" / versions["library"]).exists()
    assert (run_dir / "software" / versions["software"]).exists()
    assert not (root / "dev/fb0").read_bytes() == (bf.USB_KIT / "screens/creator5/end.img").read_bytes()


def test_script_has_lf_line_endings():
    for model in MODELS.values():
        assert "\r" not in bf.render_script(model)
