![downloader](https://socialify.git.ci/clueNA/downloader/image?font=Raleway&language=1&name=1&owner=1&pattern=Transparent&theme=Dark)
# YouTube Downloader

A clean, user-friendly YouTube video downloader web application built with **Python**, **Streamlit**, and **yt-dlp**.

## 🌐 Live Demo
[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://yt-down-loader.streamlit.app/)

## Features

- Paste any YouTube URL (videos, Shorts, embeds)
- Fetch available video resolutions (144p → 4K)
- Download video in your chosen quality (MP4, with automatic audio merge via ffmpeg)
- Download audio only (MP3, M4A, or WEBM)
- Displays video metadata: title, thumbnail, duration, channel, view count
- Real-time download progress bar with speed and ETA
- Estimated file size shown before downloading
- Automatic filename sanitization
- Friendly error messages for invalid URLs or unavailable formats

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/download.html) installed and available on your `PATH` (required for merging high-resolution video + audio streams and audio conversion)

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/clueNA/downloader.git
cd downloader

# 2. (Optional) Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
streamlit run app.py
```

The app will open automatically in your browser at `http://localhost:8501`.

## Dependencies

| Package | Purpose |
|---------|---------|
| `streamlit` | Web UI framework |
| `yt-dlp` | YouTube download backend |
| `ffmpeg-python` | Python bindings for ffmpeg (merging streams / audio conversion) |
| `requests` | HTTP utility (used transitively) |

## Project Structure

```
downloader/
├── app.py           # Main Streamlit application
├── requirements.txt # Python dependencies
└── README.md        # This file
```

## Notes

- Videos requiring age verification or login may not be downloadable.
- Downloaded files are held in memory temporarily and served via the browser's built-in download; no files are stored on the server permanently.
- High-resolution downloads (1080p, 1440p, 4K) require ffmpeg to merge the separate video and audio streams that YouTube provides for those qualities.
