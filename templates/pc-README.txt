Put PC games in here, one folder per game.

    ~/Games/pc/quake3/quake3e.x64
    ~/Games/pc/bf1942/BF1942.exe

Unlike the emulated consoles, nothing is scanned or identified automatically --
a PC game is whatever you say it is. Tell the console about it by adding an
entry to:

    ~/.local/share/pcgames.json

That file explains every field at the top of itself. The games then appear in
Kodi behind the PC GAMES entry.

Windows games
  Install them under Wine as usual and point "exec" at the .exe, or at
  ~/.local/bin/run-wine-game.sh if you want the wrapper's handling of
  prefixes and working directories.

Controllers
  Games with no gamepad support can still be played with one: JoyShockMapper
  maps a controller to keyboard and mouse. Put a config in
  ~/.config/JoyShockMapper/games/ and name it in the game's "jsm" field, and
  it is loaded while the game runs and unloaded when it exits. The CONTROLLER
  entry on the Kodi home menu edits these configs with a controller, so you
  never need a keyboard for it.

  Several ready-made configs are installed already -- look in that folder.
