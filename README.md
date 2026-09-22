# Lyrics Sync

A [Slopsmith](https://github.com/got-feedback/feedBack) plugin that generates time-synced LRC lyrics files using Whisper forced alignment against isolated vocals stems.

## How it works

1. Select a sloppak song that has split stems (vocals track required)
2. Paste or upload plain text lyrics
3. The plugin sends the vocals stem to your [Slopsmith Demucs Server](https://github.com/byrongamatos/slopsmith-demucs-server) for Whisper forced alignment
4. Preview the timestamped result, then download as `.lrc` or save directly into the sloppak for playback display

Because sloppak songs already have an isolated vocals track from Demucs separation, alignment accuracy is significantly better than aligning against a full mix.

## Features

- **Line, word, and syllable granularity** — choose the level of timing precision
- **Language hint** — optional language code to improve accuracy for non-English lyrics
- **LRC export** — standard `[mm:ss.xx] line` format compatible with any LRC player
- **Save to song** — writes synced lyrics into the sloppak manifest so they display during playback via the lyrics toggle
- **Preview panel** — review timestamps before exporting

## Requirements

- A running [Slopsmith Demucs Server](https://github.com/byrongamatos/slopsmith-demucs-server) with the `/align` endpoint (v2+)
- The demucs server URL must be configured in Slopsmith settings
- Sloppak songs with split stems (use the Sloppak Converter plugin with Demucs splitting enabled)

## Install

```bash
cd plugins
git clone https://github.com/got-feedback/feedBack-plugin-lyrics-sync.git lyrics_sync
```

Restart Slopsmith and the plugin will appear in the Plugins dropdown.
