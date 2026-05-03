# get-music

Download configured YouTube playlists as MP3 files with `yt-dlp`, then write basic MP3 metadata.

## Setup

1. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and set your YouTube Data API key:

   ```bash
   cp .env.example .env
   ```

## Usage

Run the script:

```bash
python get-music.py
```

When prompted, enter a configured playlist keyword, a playlist ID, a playlist URL, or press Enter to process every configured playlist.

To download your private YouTube Music liked songs, make sure you are logged into YouTube Music in Chrome, then enter:

```bash
liked
```

If you use a different browser for YouTube Music, pass it explicitly:

```bash
python get-music.py --cookies-browser edge
```

If Chrome says its cookie database cannot be copied, close Chrome completely and try again. If that still fails, export your YouTube cookies as a Netscape `cookies.txt` file and pass it directly:

```bash
python get-music.py --cookies-file cookies.txt
```

To only update metadata for files that already exist:

```bash
python get-music.py --metadata-only
```
