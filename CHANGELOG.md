# Changelog

All notable changes to the **Outa Music Bot** project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
