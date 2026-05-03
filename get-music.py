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
    "20260501": "PL0MiauwawbNhEphPsNS6Wcr2XipkYikZO"
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

        audio.tags["TIT2"] = TIT2(encoding=3, text=title)
        audio.tags["TPE1"] = TPE1(encoding=3, text=artist)
        audio.tags["TALB"] = TALB(encoding=3, text=album)
        audio.save()

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


def download_video_as_mp3(url: str, output_template: Path) -> None:
    subprocess.run(
        [
            "yt-dlp",
            "--extract-audio",
            "--audio-format",
            "mp3",
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
    playlist_dir = Path(folder_name)
    playlist_dir.mkdir(exist_ok=True)
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
            *cookies_args,
            url,
        ],
        check=False,
    )


def process_playlist(youtube: Any, playlist_id: str, metadata_only: bool = False) -> None:
    playlist = get_playlist_details(youtube, playlist_id)
    if not playlist:
        return

    snippet = playlist["snippet"]
    playlist_title = snippet["title"]
    safe_playlist_title = sanitize_filename(playlist_title)
    playlist_dir = Path(safe_playlist_title)
    playlist_dir.mkdir(exist_ok=True)

    print(f"Title: {playlist_title}")
    print(f"Description: {snippet['description']}")
    print(f"Published on: {snippet['publishedAt']}")
    print(f"Number of videos: {playlist['contentDetails']['itemCount']}")

    videos = get_playlist_videos(youtube, playlist_id)

    for video in videos:
        title = video["title"]
        safe_title = sanitize_filename(title)
        output_file = playlist_dir / f"{safe_title}.mp3"

        if metadata_only:
            if output_file.exists():
                print(f"Fixing metadata for '{output_file}'...")
                set_mp3_metadata(output_file, title=title, artist="YouTube", album=playlist_title)
            else:
                print(f"File '{output_file}' does not exist. Skipping.")
            continue

        print(f"Downloading '{title}'...")
        download_video_as_mp3(video["url"], playlist_dir / f"{safe_title}.%(ext)s")
        set_mp3_metadata(output_file, title=title, album=playlist_title)


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
    args = parser.parse_args()

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