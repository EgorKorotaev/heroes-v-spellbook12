# Spellbook12 development

- This repository contains only the cosmetic twelve-slot book. Campaign/API
  research and localization overlays are separate projects.
- Read `docs/AI-HANDOFF.txt`, `docs/BUILD.txt` and `docs/adr/README.md` before
  changing the book or native code. Preserve the ADR evidence and rejected probes.
- Supply game paths as arguments. Do not add personal installation paths,
  whole game archives, executables, DLLs, profiles or saves to source control.
- Keep builds read-only with respect to the game installation. Do not emit a
  patched game EXE. Native changes belong only to the verified launched process.
- Preserve exact executable/hash and original-instruction validation. Adding a
  build target requires reviewing its addresses, ABI and actual game behavior.
- Run the game-free tests. For installer changes also run Windows round trips
  in temporary folders. Use an isolated game for live checks and restore its
  temporary assets afterward. Do not deploy to a player's working installation
  merely to verify a source change.
- File/byte equivalence, startup, UI capture and gameplay are different evidence
  levels. State which actually passed; preserve untested compatibility limits.
- Installation/uninstallation must preserve unrelated and user-modified files.
- Attribute agent commits to the agent as author and committer, never to Egor.
- Remote publication needs the intended repository/account and a reviewable
  release candidate. Preparing files does not itself publish a release.
