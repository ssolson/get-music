import argparse
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from googleapiclient.discovery import build
from mutagen.id3 import ID3, TIT2, TPE1, TALB
from mutagen.mp3 import MP3
from urllib.parse import parse_qs, urlparse
from yt_dlp import YoutubeDL

# All playlist downloads and special playlists (e.g. Liked Music) go here.
MUSIC_DIR = Path("music")

# TXXX description values yt-dlp / ffmpeg often use for URL and YouTube prose.
_STRIP_TXXX_DESCS = frozenset(
    {"comment", "description", "purl", "synopsis", "artist url", "artist_url"}
)


def _strip_youtube_embedded_junk(tags: ID3) -> None:
    """Remove ID3 frames that carry YouTube descriptions, URLs, and comment fields."""
    to_delete = [
        key
        for key in tags.keys()
        if key.startswith("COMM")
        or key.startswith("USLT")
        or key.startswith("WOAR")
        or key.startswith("WXXX")
        or (
            key.startswith("TXXX:")
            and key.split(":", 1)[1].lower() in _STRIP_TXXX_DESCS
        )
    ]
    for key in to_delete:
        del tags[key]


def strip_youtube_metadata_from_file(file_path: Path) -> bool:
    """Strip YouTube URL/description metadata from one MP3. Returns True if the file was changed."""
    try:
        audio = MP3(file_path, ID3=ID3)
    except Exception as e:
        print(f"Skip '{file_path}': {e}")
        return False
    if audio.tags is None:
        return False
    before = len(audio.tags.keys())
    _strip_youtube_embedded_junk(audio.tags)
    if len(audio.tags.keys()) == before:
        return False
    audio.save(v2_version=3)
    print(f"Stripped YouTube URL/description metadata from '{file_path}'.")
    return True


def _yt_dlp_metadata_sanitize_args() -> list[str]:
    """Clear infodict fields before embed so ffmpeg writes less junk into the file."""
    return [
        "--replace-in-metadata",
        "description,comment,synopsis,purl",
        ".*",
        "",
    ]


def _yt_dlp_mp3_quality_args() -> list[str]:
    """Prefer the best YouTube audio stream and avoid yt-dlp's default lame quality (5)."""
    return [
        "-f",
        "bestaudio/best",
        "--audio-quality",
        "0",
    ]


PLAYLISTS = {
    "DJ": "PL0MiauwawbNhVsmzgtywR-yUP-sx2E9Jv",
    "Rap": "PL0MiauwawbNhqNGfISmXfvXp9EMGzVw0Z",
    "classics": "PL0MiauwawbNgl3vqto1LtQZG9pQHJM0jR",
    "EDM": "PL0MiauwawbNjdzf0y_A8UYf-8GFmOS7_Y",
    "soundtracks": "PL0MiauwawbNi_3oyYZbFz5iODn9tpTjMv",
    "Pop": "PL0MiauwawbNj1E0TrxRHchIbECDCBtu_X",
    "twang": "PL0MiauwawbNhOX8O-BJWs7K6rcodR8n2_",
    "salsa": "PL0MiauwawbNgce2es9hGV-tAneoqSy7Q2",
    "halloween": "PL0MiauwawbNjRPY43sgwWYyenioElEe3H",
    "lulu": "PL0MiauwawbNjU5Hganhb9FNrg0fWBFBBN",
    "runclub": "PL0MiauwawbNiJCWS4Y7W5EhYvyZgro58X",
    "video": "PL0MiauwawbNgNB6F4_rYeAAtgDyLTsh48",
    "birthday": "PL0MiauwawbNgdB3T531jO6KEL-wluc2xj",
    "20260501": "PL0MiauwawbNhEphPsNS6Wcr2XipkYikZO",
    "2026_summer": "PL0MiauwawbNiYcA8uELpZljJDAxvRcrFA"
}


SPECIAL_PLAYLISTS = {
    "liked": "https://music.youtube.com/playlist?list=LM",
}


def get_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("YOUTUBE_API_KEY")

    if not api_key:
        raise RuntimeError("Missing YOUTUBE_API_KEY. Add it to a .env file first.")

    return api_key


def get_playlist_selection(input_value: str) -> tuple[list[str], list[str]]:
    if not input_value:
        return list(PLAYLISTS.values()), []

    if input_value in SPECIAL_PLAYLISTS:
        return [], [SPECIAL_PLAYLISTS[input_value]]

    if input_value in PLAYLISTS:
        return [PLAYLISTS[input_value]], []

    parsed_url = urlparse(input_value)
    query_string = parse_qs(parsed_url.query)
    playlist_id = query_string.get("list", [None])[0]

    if playlist_id == "LM":
        return [], [input_value]

    return [playlist_id or input_value], []


def sanitize_filename(filename: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", filename).strip()


def set_mp3_metadata(
    file_path: Path,
    title: str,
    artist: str = "Unknown Artist",
    album: str = "YouTube Playlist",
) -> None:
    try:
        audio = MP3(file_path, ID3=ID3)

        if audio.tags is None:
            audio.add_tags()

        _strip_youtube_embedded_junk(audio.tags)
        audio.tags["TIT2"] = TIT2(encoding=3, text=title)
        audio.tags["TPE1"] = TPE1(encoding=3, text=artist)
        audio.tags["TALB"] = TALB(encoding=3, text=album)
        audio.save(v2_version=3)

        print(f"Metadata fixed for '{file_path}'.")
    except Exception as e:
        print(f"Failed to set metadata for '{file_path}': {e}")


def get_playlist_details(youtube: Any, playlist_id: str) -> dict[str, Any] | None:
    try:
        playlist_response = youtube.playlists().list(
            part="snippet,contentDetails",
            id=playlist_id,
        ).execute()
    except Exception as e:
        print(f"Error fetching playlist details for ID {playlist_id}: {e}")
        return None

    if not playlist_response.get("items"):
        print(f"No playlist found with ID {playlist_id}.")
        return None

    return playlist_response["items"][0]


def get_playlist_videos(youtube: Any, playlist_id: str) -> list[dict[str, str]]:
    next_page_token = None
    videos: list[dict[str, str]] = []

    while True:
        try:
            videos_response = youtube.playlistItems().list(
                playlistId=playlist_id,
                part="snippet",
                maxResults=50,
                pageToken=next_page_token,
            ).execute()
        except Exception as e:
            print(f"Error fetching videos for playlist ID {playlist_id}: {e}")
            break

        videos.extend(
            {
                "url": f"https://www.youtube.com/watch?v={item['snippet']['resourceId']['videoId']}",
                "title": item["snippet"]["title"],
                "video_id": item["snippet"]["resourceId"]["videoId"],
            }
            for item in videos_response.get("items", [])
        )

        next_page_token = videos_response.get("nextPageToken")
        if not next_page_token:
            break

    return videos


def _channel_title_as_artist(channel_title: str) -> str:
    """YouTube Music often uses '<Artist> - Topic' as the channel name."""
    t = channel_title.strip()
    suffix = " - topic"
    if t.lower().endswith(suffix):
        return t[: -len(suffix)].strip()
    return t


def fetch_ytdlp_album(url: str) -> str | None:
    """Album name when YouTube / YouTube Music exposes it (no download)."""
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"Warning: could not resolve album from yt-dlp for {url!r}: {e}")
        return None
    if not info:
        return None
    album = info.get("album")
    if isinstance(album, list):
        album = album[0] if album else None
    if isinstance(album, str):
        s = album.strip()
        return s or None
    return None


def hydrate_video_artists(youtube: Any, videos: list[dict[str, str]]) -> None:
    """Set each video's ``artist`` from ``videos.list`` ``channelTitle`` (up to 50 IDs per request)."""
    for i in range(0, len(videos), 50):
        chunk = videos[i : i + 50]
        ids = ",".join(v["video_id"] for v in chunk)
        try:
            resp = youtube.videos().list(part="snippet", id=ids, maxResults=50).execute()
        except Exception as e:
            print(f"Warning: could not resolve artists for batch at index {i}: {e}")
            for v in chunk:
                v["artist"] = "Unknown Artist"
            continue
        by_id = {
            item["id"]: _channel_title_as_artist(item["snippet"]["channelTitle"])
            for item in resp.get("items", [])
        }
        for v in chunk:
            v["artist"] = by_id.get(v["video_id"], "Unknown Artist")


def download_video_as_mp3(url: str, output_template: Path) -> None:
    subprocess.run(
        [
            "yt-dlp",
            "--extract-audio",
            "--audio-format",
            "mp3",
            *_yt_dlp_mp3_quality_args(),
            "--output",
            str(output_template),
            "--retries",
            "infinite",
            "--fragment-retries",
            "infinite",
            "--socket-timeout",
            "300",
            "--continue",
            "--add-metadata",
            "--embed-metadata",
            *_yt_dlp_metadata_sanitize_args(),
            "--metadata-from-title",
            "%(title)s",
            url,
        ],
        check=False,
    )


def process_special_playlist(
    url: str,
    cookies_browser: str,
    cookies_file: str | None = None,
    folder_name: str = "Liked Music",
) -> None:
    playlist_dir = MUSIC_DIR / sanitize_filename(folder_name)
    playlist_dir.mkdir(parents=True, exist_ok=True)
    cookies_args = (
        ["--cookies", cookies_file]
        if cookies_file
        else ["--cookies-from-browser", cookies_browser]
    )

    subprocess.run(
        [
            "yt-dlp",
            "--extract-audio",
            "--audio-format",
            "mp3",
            *_yt_dlp_mp3_quality_args(),
            "--output",
            str(playlist_dir / "%(title)s.%(ext)s"),
            "--retries",
            "infinite",
            "--fragment-retries",
            "infinite",
            "--socket-timeout",
            "300",
            "--continue",
            "--add-metadata",
            "--embed-metadata",
            *_yt_dlp_metadata_sanitize_args(),
            *cookies_args,
            url,
        ],
        check=False,
    )
    for mp3_path in playlist_dir.glob("*.mp3"):
        strip_youtube_metadata_from_file(mp3_path)


def process_playlist(youtube: Any, playlist_id: str, metadata_only: bool = False) -> None:
    playlist = get_playlist_details(youtube, playlist_id)
    if not playlist:
        return

    snippet = playlist["snippet"]
    playlist_title = snippet["title"]
    safe_playlist_title = sanitize_filename(playlist_title)
    playlist_dir = MUSIC_DIR / safe_playlist_title
    playlist_dir.mkdir(parents=True, exist_ok=True)

    print(f"Title: {playlist_title}")
    print(f"Description: {snippet['description']}")
    print(f"Published on: {snippet['publishedAt']}")
    print(f"Number of videos: {playlist['contentDetails']['itemCount']}")

    videos = get_playlist_videos(youtube, playlist_id)
    hydrate_video_artists(youtube, videos)

    for video in videos:
        title = video["title"]
        artist = video["artist"]
        album = fetch_ytdlp_album(video["url"]) or playlist_title
        safe_title = sanitize_filename(title)
        output_file = playlist_dir / f"{safe_title}.mp3"

        if metadata_only:
            if output_file.exists():
                print(f"Fixing metadata for '{output_file}'...")
                set_mp3_metadata(output_file, title=title, artist=artist, album=album)
            else:
                print(f"File '{output_file}' does not exist. Skipping.")
            continue

        print(f"Downloading '{title}'...")
        download_video_as_mp3(video["url"], playlist_dir / f"{safe_title}.%(ext)s")
        set_mp3_metadata(output_file, title=title, artist=artist, album=album)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Download YouTube playlists as MP3 files.")
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Fix metadata for existing MP3 files without downloading.",
    )
    parser.add_argument(
        "--cookies-browser",
        default=os.getenv("YT_DLP_COOKIES_BROWSER", "chrome"),
        help="Browser to read yt-dlp cookies from for special playlists. Defaults to chrome.",
    )
    parser.add_argument(
        "--cookies-file",
        default=os.getenv("YT_DLP_COOKIES_FILE"),
        help="Path to a Netscape cookies.txt file for special playlists.",
    )
    parser.add_argument(
        "--strip-youtube-metadata",
        nargs="*",
        metavar="DIR",
        help=(
            "Remove YouTube URL/description/comment-style metadata from MP3s under "
            "the given directories (recursive). With no directories, defaults to 'music'."
        ),
    )
    args = parser.parse_args()

    if args.strip_youtube_metadata is not None:
        dirs = [Path(d) for d in args.strip_youtube_metadata] or [MUSIC_DIR]
        for root in dirs:
            if not root.is_dir():
                print(f"Skip missing directory: {root}")
                continue
            for mp3 in root.rglob("*.mp3"):
                strip_youtube_metadata_from_file(mp3)
        return

    input_value = input(
        "Enter a playlist keyword, playlist ID, or press Enter to update all playlists: "
    ).strip()
    playlist_ids, special_urls = get_playlist_selection(input_value)

    if playlist_ids:
        youtube = build("youtube", "v3", developerKey=get_api_key())
        for playlist_id in playlist_ids:
            process_playlist(youtube, playlist_id, metadata_only=args.metadata_only)

    for url in special_urls:
        process_special_playlist(
            url,
            cookies_browser=args.cookies_browser,
            cookies_file=args.cookies_file,
        )


if __name__ == "__main__":
    main()