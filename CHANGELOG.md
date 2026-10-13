# Changelog

What changed in each version of TraceDown. The app shows a version's list the
first time it opens after updating, and the same list becomes the release notes.

## 1.6.1
- Play a player's recap from the Player Recaps list: a saved recap has a Play button that plays it in the game's player, including one downloaded a moment ago.
- A saved recap is told by its player's name in green, and the Player Recaps button on a game is green once any of that game's recaps are saved.
- The Player Recaps list only shows players who have a recap for that game.
- Opening Player Recaps goes straight to the list and shows clearly that it is loading. While a download is running it says that the list is waiting for it to finish, instead of looking stuck.
- Fixed the progress of a highlights download vanishing from a game's card after visiting a game's page and coming back.
- Automatic downloads stay on the Downloads page under Finished, saying what was saved for each game, until you clear them or close the app.

## 1.6.0
- Suggest marks: a new button above the Editor's timeline puts a first guess at where the game starts, where each break begins and ends, and where the game ends. It works from where Trace tracked the players (the field emptying for a break, everyone standing and then moving at a kick-off) and, where the referee's whistle can be heard in the saved video, puts the mark by the whistle. The guesses lean to the safe side, leaving a little standing about in sooner than cutting any play. Check each one and drag it into place; goals stay yours to mark. It can take a minute, and needs a game Trace has tracking for.
- Drag a mark along the Editor's timeline to move it: the start and end bars, the breaks and the goals. The picture follows, to show the moment the mark is on.
- Press and drag anywhere on the Editor's timeline to move through the game, instead of clicking from spot to spot. Hold Shift while dragging, the timeline or a mark, to move a tenth as fast and land on the exact moment.
- Undo and redo for the marks: Ctrl+Z and Ctrl+Shift+Z (or Ctrl+Y); on a Mac the Command key works as well.
- The Editor grows with the window: the video, the buttons and the timeline get bigger together, as far as fits on screen, and the timeline gets taller as it gets longer.
- Fullscreen Editor: a button beside the Editor's heading (or the F key) fills the screen with the video, the buttons and the timeline, and puts the settings away until you press it again or Esc.
- The Editor's mark buttons are redrawn: the game's clock (starts, break, resumes, ends) as one strip in the order it happens, each with its own icon, and a goal button for each team with that team's colour. A button shows for a moment that its mark was made.

## 1.5.4
- Fixed some games showing a gray thumbnail and "Trace has no video for this game yet" even though they play on Trace. TraceDown now uses the place Trace itself lists for each game's video instead of trying a fixed set of places.
- If a game's video still can't be found, TraceDown opens the game the way Trace's site does and reads where the video is from there.

## 1.5.3
- Fixed a download failing at the very end on Windows when a half was downloaded again, for instance after changing the quality or the sound setting partway through.
- On Windows this is also the first version with what 1.5.2 added: saving full games without sound, exporting without sound, and a player that remembers mute.

## 1.5.2
- Save full games without sound: a new switch in Settings, for games downloaded from now on. Highlights and recaps keep their sound.
- The player remembers mute and the volume from one game to the next.
- Export without sound: a switch beside the Editor's Export button leaves the sound out of the edited game.

## 1.5.1
- Fixed a full-game download ending in "Download failed" on a new install, even though the video had been saved.

## 1.5.0
- A game Editor: mark where a saved game starts, pauses, resumes and ends and where each goal was scored, enter both teams and their colours, and export the game with the breaks cut out and a score bug on top. The bug keeps the score and a running clock, grows to fit team names of any length, and can be made your own: three designs (classic, slim, colour blocks), six fonts, any size from half to double, your choice of background colour or a fade between two, square to fully round corners, a narrower or wider timer box on either side of the bar, and wider team colour strips. Add a crest for each team (beside its name) and for the league (to the left of the bug); yours and the league's come back for your next game. Save a score bug you like under a name and choose it again on any game; Reset puts every setting back. Crests can have a slight shadow, the timer's box can be as tall as the bar, and its digits can be set smaller than the score's. It slides in as the game starts and away as it ends; the picture and sound fade at each break. Point at a dot on the Editor's timeline to see what it is. Exposure, contrast and saturation sliders adjust the picture (not the bug), shown as you drag and applied to the export. The original video is never changed; the export is saved in the game's Edited folder and plays on the game's page.
- Full-game downloads now carry on where they stopped. Stop one, lose your connection, close the app or let the computer sleep, and Resume picks up from there instead of starting over. Discard throws away a download you no longer want.
- Downloads show how long is left, for the game that is running and for the games waiting in line.
- TraceDown checks that a game will fit before downloading it, and the Downloads page shows how much room is free. Automatic downloads pause and tell you once when the disk is full.
- Choose what automatic downloads fetch for each new game (the full game, highlights, player recaps) and how often they check: every hour up to once a day.
- Move downloads up and down the waiting line.
- Fixed a retry after a failed second half downloading the first half again as an extra file.
- Watch at your own speed, from quarter speed to double, and step through a moment frame by frame.
- Keyboard shortcuts on a game's page: play and pause, skip, change speed, mute, full screen, and jump between moments. Press ? to see them all.
- Full screen inside TraceDown.
- A game reopens where you stopped watching.
- Bookmark any moment of a game with a note. Your bookmarks sit on the match timeline with Trace's shots, and are kept in the game's folder.
- Cut a clip of your own: mark where it starts and ends, and it is saved to the game's My Clips folder without losing quality.
- A Storage page: see what each game takes on your disk. On a Mac you can also remove a full game, or everything for a game, from inside TraceDown; removed files go to the Trash, so they can be put back. Removal isn't offered on Windows yet.
- TraceDown notices when a saved video has been moved, renamed or deleted. Download it again, or use Find it… to show where it is now; it is left where you put it.
- Renaming a video inside a game's folder no longer loses it.
- Choose how full-game videos are named, from the date, your team and the opponent.
- A notification when a background check finds your Trace login has expired, so automatic downloads don't stop without you knowing.
- The menu-bar and tray menu now says what TraceDown is doing: the game it is downloading, or when it last checked and what it found.
- Copy a game's stats as text, or its heat map as a picture, to paste into a message.

## 1.4.2
- Fixed the Mac app opening to an empty window after updating: it now downloads the newer video engine it needs instead of trying to use the old one.

## 1.4.1
- Turning on automatic downloads now also sets TraceDown to open when you log in, so it is running to check for new games. You can still switch that off by itself in Settings.
- Turning automatic downloads off stops TraceDown opening at login.

## 1.4.0
- A welcome screen the first time you open TraceDown: pick light, dark or match your computer, and choose whether new games download automatically.
- Automatic downloads now run inside the app: every 3 hours it saves each newly added game with its highlights and player recaps. While that is on, TraceDown stays in the menu bar (Mac) or system tray (Windows) when you close the window, and can open when you log in.
- A Downloads page: start as many downloads as you like and they wait in line and run one after another, with progress, Stop, Remove and Retry.
- Heat maps: each game page can show where your players spent the game, drawn from Trace's player tracking. It works for older games too.
- New look: a sidebar for Games, Analytics, Downloads and Settings, a light theme that follows your computer, and a splash screen.
- Three ways to browse games: cards, a list, or one game at a time. Search by opponent or date, and filter by New or Saved.
- Each game shows the final score entered on Trace, with your record and goals summed up at the top.
- Every game has its own page: watch the full game, highlights and player recaps in the app, jump straight to any shot from a match timeline, and see that game's analytics underneath.
- Highlights: save a game's shots and box entries as clips plus a single Team Highlight Reel, without downloading the full game.
- Player Recaps: download Trace's follow-camera recap for any player, or all of them at once.
- Each game now has its own folder with Full Game, Highlights, Player Highlights, Analytics and Thumbnail inside.
- Analytics is a full season page laid out like a game page: your record and goals, a season timeline with a dot for every game, season totals with per-game averages, game-by-game charts, and touches per player. Stats are saved, so they stay after Trace stops serving them and open quickly.
- Watch Game and Open Folder buttons on downloaded games, a Retry button and a reason when a download fails, and a notification when downloads finish.
- Your computer stays awake while a download is running.
- A download that is interrupted is never mistaken for a finished one.
- TraceDown can now update itself: it tells you when a new version is ready and installs it when you choose.
