# Changelog

All notable changes to the **Outa Music Bot** project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.9.1] - 2026-06-26
### Added
- **New Command**: Added `!new` (`!latest`, `!update`) command to display the latest changelog and current bot version.
### Changed
- **Cleaned up code**: Removed unused imports and code.

## [1.9.0] - 2026-06-23
### Changed
- **Autoplay Removed**: The background `autoplay` mechanism (and the `!autoplay` command) has been completely removed to simplify queue management. The bot will now respect the exact tracks requested and will automatically disconnect after the queue is empty and the inactivity timer expires.
- **Mix Command Overhaul**: The `!mix <query>` (or `!m`) command has been repurposed. Instead of starting an endless autoplay loop, it now acts as a batch importer. It immediately searches and fetches the top 10 tracks matching the given artist or genre and queues them all at once.

## [1.8.1] - 2026-06-20
### Changed
- **Smart Lyrics Detection**: The `!player` and `!subs` commands now automatically detect if a track originates from YouTube Music. If it does, the `!player` embed hides the subtitles section and suggests using `!lyrics`, and the `!subs` command redirects users to `!lyrics`.
- **Lyrics & Subs Language Hints**: Added helpful language code hints (`id`, `jp`, `rj`, `en`, `zh`, `ko`) to `!lyrics` and `!subs` command messages to make translation easier.
- **Interactive Search Update**: The `!show` command's interactive menu now automatically deletes itself after a track is selected or when it times out (20 seconds) to keep the chat clean.
- **Dedicated YouTube Commands**: Menambahkan command baru `!ytplay` dan `!ytshow` untuk melakukan pencarian khusus di YouTube standar. Sementara itu, command utama `!play` dan `!show` sekarang difokuskan murni untuk mencari Official Tracks di YouTube Music.

## [1.8.0] - 2026-06-20
### Added
- **Lyrics API Integration**: Added a dedicated `!lyrics` (`!ly`) command to fetch track lyrics and translations.
- **Dockerized Lyrics Service**: Integrated `LyricsApi.jar` into the `docker-compose.yml` to run locally and serve the music bot's requests.

## [1.7.2] - 2026-06-20
### Added
- **Interactive Search**: Added `!show` (`!s`) command to search for tracks and view results in an interactive dropdown menu before playing or adding to the queue.
- **Bot Version Command**: Added `!version` (`!ver`) command to view the current bot version and changelog.
- **Voice Filter**: Added a `voice` filter (`!filter voice`) that isolates the mid-channel and applies a bandpass filter to emphasize vocals and reduce instruments.
- **Command Shortcuts**: Added new aliases: `!vol` (volume), `!q` (queue), `!sk` (skip), `!sh` (shuffle).

### Changed
- **Filter and Speed Display**: Running `!filter` or `!speed` without arguments now displays the currently active setting and valid options.
- **Queue Drop Enhancement**: `!drop` now accepts `last` or `0` to remove the very last track in the queue.
- **Clear Confirmation**: `!clear` now prompts the DJ with an interactive Confirm/Cancel button view before wiping the queue.

## [1.7.1] - 2026-06-18
### Added
- **Title Sanitization**: Introduced `clean_title` to remove invisible Unicode characters and strip trailing spaces from track titles, ensuring cleaner UI display.
- **Subtitle Deduplication**: Implemented `deduplicate_lines` to filter out duplicate lines and merge overlapping words/sentences when fetching subtitles via the `!subs` command.

## [1.7.0] - 2026-06-18
### Added
- **Audio Speed Control**: Added a new `!speed <value>` command to dynamically control the audio playback speed from `0.1x` to `2.0x`. Setting it to `normal` or `clear` resets the speed to `1.0x`.
- **Chained FFmpeg Filters**: Modified the audio filter system to combine speed adjustments with active audio filters (like bassboost or nightcore) smoothly using FFmpeg filter chains.
- **Speed-Aware Playback Tracker**: Recalibrated the track progress bar (`get_elapsed`) to accurately track time based on the active speed setting.

## [1.6.2] - 2026-06-18
### Changed
- **Karaoke Filter Improvement**: Upgraded the basic phase-inversion vocal remover into a professional multi-band crossover network. It splits the audio to isolate and preserve low-frequency bass and kick drums (below 150Hz) while applying phase cancellation exclusively to the mid/high frequencies (above 150Hz). It also outputs in-phase mono signals for safe compatibility on mono speakers.

## [1.6.1] - 2026-06-18
### Changed
- **Player Interface Redesign**: Converted the vertical "Details" list block inside the `Now Playing` embeds into individual inline fields (`Tags`, `Subtitles`, `Uploaded`). This aligns them horizontally side-by-side (sideways) with other fields like `Channel` and `Duration`, creating a cleaner card interface.

## [1.6.0] - 2026-06-18
### Changed
- **Metadata Tags**: Replaced "Genre" display and logic with YouTube "Tags". The player now shows up to 3 tags of the playing track (or None if not available) instead of a single category genre.
- **Autoplay Refactoring**: Refactored the Autoplay query logic to use the first tag of the previously played track when generating subsequent search queries.
- **Credit Command Code Refactoring**: Introduced a global `BOT_VERSION` variable at the module level in `cogs/music.py`, allowing the `!credit` command to dynamically fetch the version instead of hardcoding it.
- **Command Parameter Update**: Updated references of "genre" to "tag" in the `!autoplay` command and the helper page listing.

## [1.5.0] - 2026-06-18
### Added
- **YouTube Music Prioritization**: Default search queries now prioritize YouTube Music (`https://music.youtube.com/search?q=...`) rather than regular YouTube to return official music track formats first. Added a filtering system to discard non-playable search results (like artist channels and empty albums) and only queue playable tracks. This applies to both the `!play` command and Autoplay.

### Fixed
- **HTTP 403 Forbidden Error**: Resolved streaming playback and seeking failures by passing yt-dlp extracted HTTP headers (including User-Agent) directly to FFmpeg options.

## [1.4.0] - 2026-06-18
### Added
- **Subtitles/Lyrics Support**: Added a `!subs` (or `!subtitle`, `!lyrics`) command that fetches and downloads `.json3` or `.vtt` subtitles/captions directly from YouTube. Subtitles are parsed and sent to the channel as a `.txt` file attachment.
- **Dependencies**: Added `aiohttp` to `requirements.txt` to handle asynchronous subtitle downloading.

### Fixed
- **Autoplay Infinite Loop Bug**: Built a robust fail-safe mechanism into the Autoplay system. If tracks fail to extract or immediately crash during playback (duration < 3s) for 3 consecutive times, the bot automatically disables autoplay to prevent infinite searching and API spamming loops.
- **Karaoke Filter Syntax**: Fixed an FFmpeg syntax error (`Expected in channel name`) in the `karaoke` audio filter by implementing standard phase-inversion channel mapping (`pan=stereo|c0=c0-c1|c1=c1-c0`).

### Changed
- **Dynamic Player Re-rendering**: The bot now intelligently deletes its old player message and sends a fresh one at the bottom of the chat whenever a new song starts playing, ensuring the player is always visible without scrolling. The player is also cleanly deleted when playback is stopped or the queue finishes.
- **Player Interface Improvements**: 
  - Integrated rich YouTube video thumbnails into the `Now Playing` embeds. 
  - Reorganized the layout to beautifully group `Genre`, `Subtitles`, and `Uploaded` details together rather than splitting them across the footer.

## [1.3.1] - 2026-06-18
### Changed
- **Help Command**: Added spacing between the help header and category titles, and updated the `!filter` command to explicitly list all available filter options.

## [1.3.0] - 2026-06-18
### Added
- **Autoplay System**: 
  - `!autoplay [genre]`: Toggles smart autoplay. If the queue is empty, the bot automatically fetches and plays related music. It can optionally be locked to a specific genre.
  - Implemented an internal history tracker to guarantee the bot does not loop the same tracks.
- **Audio Filters**: 
  - `!filter <name>`: Injected FFmpeg parameters to dynamically apply real-time sound filters (`bassboost`, `nightcore`, `vaporwave`, `karaoke`, `8d`).
  - Added a `clear` filter to revert to normal playback.

## [1.2.1] - 2026-06-18
### Changed
- **Help Command Redesign**: Reorganized the `!help` command output. Commands are now grouped by category (Playback Controls, Queue Management, Session & Utilities) and listed one command per line for much better readability.
- **Credit Versioning**: Added the current bot version display to the `!credit` command.

## [1.2.0] - 2026-06-18
### Documentation
- **Comprehensive README Update**: Overhauled the `README.md` file to properly document the new feature set, updated the feature highlights, and clarified setup instructions for both local and Docker environments. Added a link pointing to this `CHANGELOG.md`.

## [1.1.2] - 2026-06-16
### Refactoring
- **AI Attribution**: Changed the creator's AI reference from 'AI' to 'Gemini AI' to accurately reflect the development tools used in creating this project.
- **Minor Bug Fixes**: Cleaned up various code segments for better readability and slightly optimized the codebase for stability.

## [1.1.1] - 2026-06-16
### Added
- **Looping System**:
  - `!loop`: Toggles a continuous loop for the currently playing track.
  - `!loopqueue` (`!lq`): Toggles looping for the entire queue. Preserves track order dynamically even when the queue shifts.
- **Replay Feature**: 
  - `!replay` (or `!previous`): Replays the previously played track without losing the current queue's progression. It seamlessly rewinds the timeline.
- **Stop Command**:
  - `!stop`: Instantly stops the playback, turns off all active loops, and clears the entire queue simultaneously.
- **DJ Session Transfer**:
  - `!transfer <@user>`: Allows the current DJ session owner to transfer their administrative privileges (playback control) to another member in the voice channel.

## [1.1.0] - 2026-06-16
### Added
- **DJ / Session Ownership System**: Implemented strict authorization logic. Only the user who requested the very first track (the session owner) or a user with `Administrator` guild permissions is allowed to control the bot's playback features (such as `!pause`, `!skip`, `!stop`, `!clear`, etc.).
- `!dj`: A new command to check who the current DJ (session owner) is.
- **Inactivity Auto-Disconnect**: Integrated an automated cleanup mechanism. The bot will automatically disconnect from the voice channel and clear its session cache if left completely alone (no human users) for a specific duration or if the queue finishes and 2 minutes pass without new requests.

## [1.0.1] - 2026-06-16
### Fixed
- **Dependency Issues**: Fixed configuration issues relating to `pip` packages.
- **Environment Handling**: Included `python-dotenv` explicitly in `requirements.txt` to guarantee smooth environment variable parsing for the Discord Bot Token across different operating systems.

## [1.0.0] - 2026-06-16
### Added
- **Initial Release**: The core architecture and functional release of the Outa Discord Music Bot built using `discord.py` and `yt-dlp`.
- **Infrastructure & Deployment**:
  - Configured project environment safely utilizing a `.env` file (`BOT_TOKEN`).
  - Added `Dockerfile` and `docker-compose.yml` for simplified, 1-click containerized deployment.
  - Setup core FFmpeg audio streaming and conversion options (`-reconnect`, `-vn`, etc.).
- **Smart Queue & Playback**:
  - `!play <query/url>`: Resolves YouTube search queries or direct URLs and queues them for playback. Includes batch indexing (up to 5 URLs at a time) and handles YouTube playlists.
  - **Pre-fetching System**: The bot quietly resolves and fetches the metadata of the next track in the queue in the background. This ensures completely gapless playback with zero buffering between tracks.
- **Advanced Playback Controls**:
  - `!pause` & `!resume`: Standard audio pause and playback resumption logic.
  - `!skip [index]`: Skips the current track or immediately skips to a specific track index in the queue.
  - `!seek <time>`: Rewinds or fast-forwards to an exact timestamp within the current track (supports both seconds `90` or time-format `01:30`).
  - `!forward <seconds>` & `!back <seconds>`: Skips the audio forward or backward by a specified number of seconds (defaults to 5 seconds).
  - `!volume <1-100>`: Dynamically adjusts the bot's output volume.
- **Queue Management**:
  - `!queue`: Displays the queue with interactive pagination. Long queues are split across multiple pages, navigable using `Previous` and `Next` Discord UI buttons.
  - `!drop <indices>`: Powerful command to drop specific tracks or a range of tracks from the queue (e.g., `!drop 1,3,5-7`).
  - `!clear`: Instantly clears all upcoming tracks.
  - `!shuffle`: Randomizes the current queue order.
  - `!move <from> <to>`: Relocates a track from one index to another within the queue.
- **User Interface & Tracking**:
  - `!player` (or `!np`): Renders a rich embed of the "Now Playing" track. Includes current timestamp progress vs total duration, uploader channel, total view counts, music genre, and subtitle availability detection (`EN`, `ID`, `JP`, `KR`).
  - **Live Tagging**: Detects and properly tags YouTube Livestreams with `🔴 [LIVE]` tags.
- **Utilities**:
  - `!ping`: Calculates and evaluates the bot's WebSocket latency to the Discord Gateway.
  - `!credit`: Shows the bot creator's credits and GitHub repository link.
  - `!help`: Neatly paginated interactive help menu showcasing all available commands.
  - `!quit` (or `!leave`, `!disconnect`): Safely disconnects the bot and cleans up the voice client.
