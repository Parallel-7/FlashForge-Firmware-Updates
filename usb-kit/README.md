# USB kit

This folder holds the parts of the USB update file. [`tools/build_flashable.py`](../tools/build_flashable.py) puts them together for each release.

- `install.sh.in`: the template for the update script. The build tool fills in the values for each printer model.
- `screens/`: FlashForge's stock "Upgrading" (`start.img`) and "Upgrade completed" (`end.img`) screens.
  - `landscape/`: Adventurer 5M, Adventurer 5M Pro and Adventurer 5X.
  - `creator5/`: Creator 5 and Creator 5 Pro (portrait display).
- `play/`: FlashForge's stock beep program.
  - `arm/`: Adventurer 5M and Adventurer 5M Pro.
  - `mips/`: Adventurer 5X, Creator 5 and Creator 5 Pro.

All files in `screens/` and `play/` come from official FlashForge firmware packages. All rights to them belong to FlashForge.

## What the update script does

1. Stops if the printer is a different model.
2. Checks every package (MD5). If a check fails, the script stops before it changes anything.
3. Shows the "Upgrading" screen.
4. Installs the firmware packages, the same way FlashForge's own USB update does.
5. Shows the "Upgrade completed" screen and beeps.

The script does not change the root password, `inittab`, `printer.cfg` or user files.
