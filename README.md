# FlashForge Firmware Updates

A permanent, bot-maintained mirror of FlashForge printer firmware packages.

FlashForge's OTA servers are **latest-only** — the download URLs they hand out
rotate and eventually stop resolving. This repo exists so that every firmware
version the [FlashForge community Discord bot](https://github.com/Parallel-7) has
ever observed stays downloadable, forever, via stable GitHub release links.

## How it works

When the bot detects a new firmware release for a supported printer, it:

1. Downloads each package's `.xz` from the FlashForge OTA server.
2. Verifies the bytes against the OTA-provided MD5 checksum.
3. Publishes the files as **GitHub Release assets** (these never expire, have no
   bandwidth limit, and require no authentication to download).
4. Records the release here and announces it in Discord using the permanent links.

Binaries live **only** as release assets — they are never committed into the git
tree. This keeps the repository lightweight and the download URLs on GitHub's CDN
(which is not rate-limited the way `raw.githubusercontent.com` is).

## Supported printers

| Model               | Slug                |
|---------------------|---------------------|
| Adventurer 5M       | `adventurer-5m`     |
| Adventurer 5M Pro   | `adventurer-5m-pro` |
| Adventurer 5X       | `adventurer-5x`     |
| Creator 5           | `creator-5`         |
| Creator 5 Pro       | `creator-5-pro`     |

## Release / tag format

Each firmware release is one GitHub Release, tagged:

```
<model-slug>/<software-version>-<control-version>
```

This mirrors FlashForge's own OEM naming convention
(e.g. `Adventurer5M-3.2.6-2.2.3`). The `library` and `kernel` packages ship as
assets of the same release but are deliberately **not** part of the version
identity (same as FlashForge treats them).

Examples:

| Tag                                | Assets                                             |
|------------------------------------|----------------------------------------------------|
| `adventurer-5m/5.1.4-2.2.3`        | `software-5.1.4.xz`, `control-2.2.3.xz`, `library-2.5.0.xz` |
| `creator-5-pro/1.9.4-1.2.6`        | `software-1.9.4.xz`, `control-1.2.6.xz`            |
| `adventurer-5x/3.1.0-1.1.1`        | `software-3.1.0.xz`, `control-1.1.1.xz`, `library-2.0.1.xz` |

## Downloading

Download URLs follow the form:

```
https://github.com/Parallel-7/FlashForge-Firmware-Updates/releases/download/<tag>/<asset>
```

These are direct CDN links — no authentication, no per-IP rate limit. See the
[Releases page](../../releases) for the full catalog.

## Firmware index

> The section below is regenerated automatically by the bot whenever a new
> release is published. Do not edit it by hand.

<!-- BOT-GENERATED-INDEX-START -->
_No releases have been published yet._

<!-- BOT-GENERATED-INDEX-END -->

## Notes

- The firmware packages redistributed here are produced by **FlashForge**; all
  rights to the firmware itself belong to FlashForge. This mirror exists solely
  to preserve access to versions that FlashForge's latest-only OTA no longer
  serves.
- If the bot is ever unable to reach GitHub, it gracefully falls back to the
  live OTA links in Discord — it never goes silent.
