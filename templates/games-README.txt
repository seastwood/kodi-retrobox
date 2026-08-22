Put your games in here, one folder per system.

    ~/Games/emulation/snes/Super Mario World (USA).sfc
    ~/Games/emulation/sega-genesis/Sonic The Hedgehog (USA, Europe).md
    ~/Games/emulation/playstation/Final Fantasy VII (USA)/...cue

A game may sit loose in the system folder or in a folder of its own; both work.

Within ten minutes the sync timer will find it, identify it, download its box
art, work out how many players it takes and add it to the Kodi menu. Nothing
needs restarting. To make it happen immediately:

    ~/.local/bin/sync_games.py

Notes
  * The folder name is a convention, not a rule. RetroArch identifies games by
    hashing them, so a game in the "wrong" folder is still filed correctly.
  * Compressed disc images (.ciso, .chd) cannot be identified by hash. They
    still work, they just get their name from the filename.
  * Multi-disc games: keep every disc in one folder named "... (Disc 1)",
    "... (Disc 2)". They are joined into a single entry you can swap discs in
    from RetroArch's own menu. A set with discs missing is reported as
    INCOMPLETE by the sync.
  * BIOS files do NOT go here. They go in
    ~/.local/share/retroarch/system/ -- see system/bios-required.txt in the
    repository. A BIOS left in a ROM folder is dropped from the playlist.
