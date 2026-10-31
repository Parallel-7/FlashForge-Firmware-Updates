# FlashForge Firmware Updates

Download FlashForge firmware for your printer, including old versions.
Each version comes with a ready-to-use USB update file.

Printers: Adventurer 5M, Adventurer 5M Pro, Adventurer 5X (AD5X), Creator 5 and Creator 5 Pro.

## Pick your printer

Find your printer in the table. Download its USB update file. Then follow the [USB steps](#update-with-a-usb-drive).

<!-- index:start -->
_The table appears after the next index update._
<!-- index:end -->

## Update with a USB drive

The USB update installs the stock FlashForge firmware. It does not change your printer settings or your files.

1. Format a USB drive as FAT32.
2. Download the USB update file (`.tgz`) for your printer.
3. Copy the file to the root folder of the USB drive (the top level, not inside a folder).
   Do not rename the file. Do not extract it.
4. Make sure that the USB drive has only one `.tgz` file for your printer.
5. Turn off the printer.
6. Put the USB drive into the printer.
7. Turn on the printer. The update starts automatically and the "Upgrading" screen appears.
8. Wait for the "Upgrade completed" screen.
9. Remove the USB drive. If you leave it in, the printer installs the update again at the next start.
10. Restart the printer.

> [!WARNING]
> **Creator 5 and Creator 5 Pro:** FlashForge says that you cannot roll back firmware 2.0.0 to 1.9.8 or earlier.
> This applies to online updates and USB updates. A rollback can cause errors.
> Older Creator 5 releases in this mirror carry this warning too.

### If the update does not start

Check these items:

- The USB drive is formatted as FAT32. The printer cannot read other formats.
- The file is in the root folder, not in a subfolder.
- The file name is unchanged, for example `Creator5-2.0.0-1.3.0.tgz`.
- The file is a `.tgz` file. The printer cannot read `.zip` files.
- The USB drive has only one `.tgz` file for your printer. If it has more, the printer installs only the newest one.

## Files in each release

Each firmware version is one GitHub release. The tag is `<printer>/<software>-<control>`, for example `creator-5/2.0.0-1.3.0`.

| File | For | What it is |
|---|---|---|
| `<Machine>-<software>-<control>.tgz` | Everyone | The USB update file. It is first in the list of release files. |
| `raw-<package>-<version>.xz` | Developers | An original package from FlashForge's update server (`kernel`, `control`, `library` or `software`). It is a plain tar archive, despite the `.xz` name. |

The USB update file holds the stock FlashForge packages, an update script and the stock update screens.
If a release did not change a package, the USB update file includes that package from an earlier release with the same version.
So each USB update file is a complete set.

The update script:

- Stops if the file is for a different printer model.
- Checks every package (MD5) before it changes anything.
- Installs only the firmware packages, the same way FlashForge's own USB update does.
- Does not change the root password, `inittab`, `printer.cfg` or user files.

Each printer has a page with every version, in the [`printers/`](printers/) folder.

## How this mirror works

1. A Discord bot checks FlashForge's update servers for new firmware.
2. The bot publishes each new version here as a release.
3. A [GitHub Action](.github/workflows/release.yml) builds the USB update file with [`tools/build_flashable.py`](tools/build_flashable.py).
4. The same Action updates the index with [`tools/build_index.py`](tools/build_index.py).

The update script template is [`usb-kit/install.sh.in`](usb-kit/install.sh.in). See the [USB kit notes](usb-kit/README.md).

## Notice

FlashForge makes this firmware. All rights to the firmware belong to FlashForge.
This mirror is unofficial.
FlashForge's update servers offer only the newest version to printers. This mirror keeps the old versions available.
Use these files at your own risk.
