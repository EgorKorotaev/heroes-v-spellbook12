Heroes V Spellbook12 — 0.1.0-beta.1

Twelve spells per spread in the native 3D spellbook: two columns by three rows
on each leaf, filled row by row. Original art, animation and icons are retained;
text wrapping, spell selection margins and tooltip anchors are adjusted.

Supported player packages:
  Universe 2.0.1: exact reviewed bin/H5_Game.exe.
  Heroes 5.5 RC19k: exact reviewed bin/MMH55_64.exe.
Executable identity is checked using SHA-256 and instruction bytes. Other game
builds and Utility targets are not covered by this player release.

Windows installation:
  Close the game. Fully extract the matching ZIP. Run Install.cmd and select
  the game root containing bin and data. Launch using Spellbook12 - Play in
  the game folder, or Spellbook12/Launch.cmd. Wait for Spellbook12 is ready
  before starting or loading a game. Python is not required for the player package.

The installer adds only its own Spellbook12 directory and data/Spellbook12.pak.
It does not rewrite the game EXE, base archives, maps or saves. Runtime changes
exist only in the newly launched process. Starting the EXE/lobby directly does
not apply this mod's runtime component. Both layers must be active together;
uninstall the mod before playing without its launcher. Window/profile settings
are not forced.

To remove: close the game, then run Spellbook12/Uninstall.cmd. Modified owned
files stop removal; unrelated files are retained. For this initial beta, remove
the previous installation before updating. Old Spellbook12-grid.pak and
Spellbook12-H55.pak test overlays must be backed up and removed separately.

The preceding working book was checked in adventure and combat views, including
twelve-slot interactions and an explicit seventh-slot combat cast. Historical
tests mainly used a 1280x960 window and Russian text. Multiplayer, H5Lobby launch,
all resolutions/localizations and other interface mod combinations are untested.
The native clip's small right-leaf endpoint settle is retained; it also occurs
with the original six-slot book. Old-page text bleed is repaired by giving the
turning paper a small thickness, preserving the static spell layout and icons.
See VALIDATION.txt for checks performed on this particular release candidate.

Developer source: docs/BUILD.txt, docs/AI-HANDOFF.txt and docs/adr/README.md.
Original project code is MIT; game-derived resources have separate provenance
described in NOTICES.txt. No original game EXE, DLL or full archive is included.
