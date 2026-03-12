"""
YouTube Video Downloader - Streamlit Web Application
=====================================================
A clean, user-friendly web app built with Streamlit and yt-dlp that lets
users download YouTube videos or audio in their preferred quality.

Run locally:
    streamlit run app.py
"""

import io
import os
import re
import tempfile
import threading
import unicodedata

import streamlit as st
import yt_dlp

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="YouTube Downloader",
    page_icon="▶️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AUDIO_FORMAT_OPTIONS = ["MP3", "M4A", "WEBM"]

# Resolution labels shown in the dropdown when NOT in audio-only mode
RESOLUTION_LABELS = ["Best available", "4K (2160p)", "1440p", "1080p", "720p", "480p", "360p", "240p", "144p"]

# Map a human-readable label to a yt-dlp format selector string
RESOLUTION_FORMAT_MAP = {
    "Best available": "bestvideo+bestaudio/best",
    "4K (2160p)": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "1440p": "bestvideo[height<=1440]+bestaudio/best[height<=1440]",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "240p": "bestvideo[height<=240]+bestaudio/best[height<=240]",
    "144p": "bestvideo[height<=144]+bestaudio/best[height<=144]",
}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Return a filesystem-safe version of *name*.

    - Normalise unicode characters to ASCII equivalents where possible.
    - Replace characters that are illegal on common filesystems with ``_``.
    """
    # Normalise unicode (e.g. accented chars → ASCII)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    # Replace anything that is not alphanumeric, space, hyphen, or dot
    name = re.sub(r"[^\w\s\-.]", "_", name)
    # Collapse multiple underscores / spaces
    name = re.sub(r"[\s_]+", "_", name).strip("_")
    return name or "download"


def is_valid_youtube_url(url: str) -> bool:
    """Return *True* if *url* looks like a valid YouTube video URL."""
    patterns = [
        r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[\w\-]{11}",
        r"(https?://)?(www\.)?youtube\.com/shorts/[\w\-]{11}",
        r"(https?://)?(www\.)?youtube\.com/embed/[\w\-]{11}",
        r"(https?://)?(m\.)?youtube\.com/watch\?v=[\w\-]{11}",
    ]
    return any(re.search(p, url) for p in patterns)


def format_duration(seconds: int) -> str:
    """Convert *seconds* to a human-readable ``HH:MM:SS`` or ``MM:SS`` string."""
    if seconds is None:
        return "N/A"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_filesize(size_bytes) -> str:
    """Format *size_bytes* as a human-readable string (e.g. ``45.3 MB``)."""
    if size_bytes is None:
        return "Unknown"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ---------------------------------------------------------------------------
# yt-dlp helpers
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=300)
def fetch_metadata(url: str) -> dict:
    """Fetch video metadata (without downloading) using yt-dlp.

    Results are cached for 5 minutes to avoid repeated network calls.
    Returns a dict with keys: title, thumbnail, duration, channel, formats.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info


def build_format_table(info: dict) -> list[dict]:
    """Extract video-only formats from *info* and return them sorted by height."""
    formats = info.get("formats", [])
    video_formats = []
    seen_heights = set()

    for fmt in formats:
        vcodec = fmt.get("vcodec", "none")
        height = fmt.get("height")
        # Skip audio-only, formats without height info, or duplicates
        if vcodec in (None, "none") or not height or height in seen_heights:
            continue
        seen_heights.add(height)
        filesize = fmt.get("filesize") or fmt.get("filesize_approx")
        video_formats.append(
            {
                "height": height,
                "label": f"{height}p",
                "ext": fmt.get("ext", ""),
                "filesize": filesize,
                "filesize_str": format_filesize(filesize),
                "format_id": fmt.get("format_id", ""),
            }
        )

    # Sort descending by resolution
    video_formats.sort(key=lambda x: x["height"], reverse=True)
    return video_formats


class ProgressTracker:
    """Thread-safe container that records yt-dlp download progress."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.percent: float = 0.0
        self.speed: str = ""
        self.eta: str = ""
        self.status: str = "starting"
        self.filename: str = ""
        self.total_bytes: int | None = None
        self.downloaded_bytes: int = 0

    def hook(self, d: dict) -> None:
        """Progress hook passed to yt-dlp."""
        with self._lock:
            self.status = d.get("status", "unknown")
            if self.status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                self.total_bytes = total
                self.downloaded_bytes = downloaded
                if total:
                    self.percent = downloaded / total
                speed_raw = d.get("speed")
                self.speed = format_filesize(speed_raw) + "/s" if speed_raw else ""
                eta_raw = d.get("eta")
                self.eta = f"{eta_raw}s" if eta_raw else ""
                self.filename = d.get("filename", "")
            elif self.status == "finished":
                self.percent = 1.0
                self.filename = d.get("filename", "")


def download_media(
    url: str,
    fmt_selector: str,
    output_dir: str,
    audio_only: bool = False,
    audio_format: str = "mp3",
    tracker: ProgressTracker | None = None,
) -> str:
    """Download a video/audio from *url* and return the path to the output file.

    Parameters
    ----------
    url:
        YouTube video URL.
    fmt_selector:
        yt-dlp format selector string (ignored when *audio_only* is True).
    output_dir:
        Directory where the downloaded file will be saved.
    audio_only:
        When True, download and convert to the specified *audio_format*.
    audio_format:
        One of ``mp3``, ``m4a``, or ``webm`` (used when *audio_only* is True).
    tracker:
        Optional :class:`ProgressTracker` instance to collect progress info.
    """
    outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

    ydl_opts: dict = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        # Merge video+audio when separate streams are required
        "merge_output_format": "mp4",
    }

    if tracker:
        ydl_opts["progress_hooks"] = [tracker.hook]

    if audio_only:
        ydl_opts["format"] = "bestaudio/best"
        af = audio_format.lower()
        if af == "mp3":
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
        elif af == "m4a":
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                    "preferredquality": "192",
                }
            ]
        # For WEBM we keep the native audio stream as-is (no post-processing)
    else:
        ydl_opts["format"] = fmt_selector

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # Determine where yt-dlp actually wrote the file
        prepared = ydl.prepare_filename(info)

    # yt-dlp may change the extension after post-processing; find the real file
    base_no_ext = os.path.splitext(prepared)[0]
    if audio_only and audio_format.lower() != "webm":
        candidate = f"{base_no_ext}.{audio_format.lower()}"
        if os.path.exists(candidate):
            return candidate
    # Otherwise return the merged/prepared filename (mp4 for video)
    mp4_candidate = f"{base_no_ext}.mp4"
    if os.path.exists(mp4_candidate):
        return mp4_candidate
    if os.path.exists(prepared):
        return prepared
    # Last resort: find the most recently modified file with a known extension
    known_exts = {".mp4", ".mp3", ".m4a", ".webm", ".mkv", ".opus"}
    candidates = [
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if os.path.splitext(f)[1].lower() in known_exts
    ]
    if candidates:
        return max(candidates, key=os.path.getmtime)
    raise FileNotFoundError("Downloaded file could not be located.")


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def render_metadata(info: dict) -> None:
    """Render video thumbnail, title, duration and channel name."""
    col_thumb, col_info = st.columns([1, 2])
    with col_thumb:
        thumbnail = info.get("thumbnail")
        if thumbnail:
            st.image(thumbnail, use_container_width=True)
    with col_info:
        st.markdown(f"### {info.get('title', 'Unknown title')}")
        st.markdown(f"**Channel:** {info.get('uploader', 'N/A')}")
        st.markdown(f"**Duration:** {format_duration(info.get('duration'))}")
        view_count = info.get("view_count")
        if view_count:
            st.markdown(f"**Views:** {view_count:,}")


def render_formats_table(formats: list[dict]) -> None:
    """Display available video resolutions in a compact info block."""
    if not formats:
        st.info("No separate video streams found — 'Best available' will be used.")
        return
    lines = ["| Resolution | File size |", "|---|---|"]
    for f in formats:
        lines.append(f"| {f['label']} | {f['filesize_str']} |")
    st.markdown("\n".join(lines))


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

def main() -> None:
    # ---- Page header -------------------------------------------------------
    st.title("▶️ YouTube Downloader")
    st.markdown(
        "Paste a YouTube URL, choose your quality, and download the video or audio."
    )
    st.divider()

    # ---- URL Input ---------------------------------------------------------
    url = st.text_input(
        "YouTube URL",
        placeholder="https://www.youtube.com/watch?v=...",
        help="Paste any YouTube video, Shorts, or embed URL.",
    )

    fetch_clicked = st.button("🔍 Fetch Formats", type="primary", use_container_width=True)

    # ---- Validate URL when the button is clicked or already in session -----
    if fetch_clicked and url:
        if not is_valid_youtube_url(url):
            st.error("❌ The URL doesn't look like a valid YouTube link. Please check and try again.")
            st.stop()
        # Clear any previously cached state when a new URL is submitted
        if st.session_state.get("last_url") != url:
            for key in ("info", "formats", "last_url"):
                st.session_state.pop(key, None)
        st.session_state["last_url"] = url

        with st.spinner("Fetching video information…"):
            try:
                info = fetch_metadata(url)
                st.session_state["info"] = info
                st.session_state["formats"] = build_format_table(info)
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as exc:
                st.error(f"❌ Could not fetch video information: {exc}")
                st.stop()
            except yt_dlp.utils.YoutubeDLError as exc:
                st.error(f"❌ yt-dlp error: {exc}")
                st.stop()
            except Exception as exc:  # noqa: BLE001 — catch-all for truly unexpected errors
                st.error(f"❌ Unexpected error: {exc}")
                st.stop()

    # ---- If we have metadata, show the rest of the UI ----------------------
    if "info" not in st.session_state:
        st.stop()

    info: dict = st.session_state["info"]
    formats: list[dict] = st.session_state["formats"]

    st.divider()
    render_metadata(info)
    st.divider()

    # ---- Format selection --------------------------------------------------
    st.subheader("⚙️ Download Options")

    audio_only = st.checkbox("🎵 Audio only", value=False)

    col_left, col_right = st.columns(2)

    with col_left:
        if audio_only:
            audio_format = st.selectbox("Audio format", AUDIO_FORMAT_OPTIONS)
            fmt_selector = ""  # not used for audio-only
        else:
            resolution = st.selectbox("Video resolution", RESOLUTION_LABELS)
            fmt_selector = RESOLUTION_FORMAT_MAP[resolution]
            audio_format = "mp3"  # unused

    with col_right:
        if not audio_only and formats:
            st.markdown("**Available resolutions**")
            render_formats_table(formats)

    # ---- Estimated file size (best effort) ---------------------------------
    if not audio_only and formats:
        selected_height_match = re.search(r"(\d+)p", resolution)  # safe: inside `if not audio_only`
        if selected_height_match:
            target_height = int(selected_height_match.group(1))
            closest = min(
                (f for f in formats if f["height"] <= target_height),
                key=lambda x: target_height - x["height"],
                default=None,
            )
            if closest and closest["filesize"]:
                st.info(f"💾 Estimated file size: ~{closest['filesize_str']}")

    st.divider()

    # ---- Download ----------------------------------------------------------
    download_clicked = st.button("⬇️ Download", type="primary", use_container_width=True)

    if download_clicked:
        title_safe = sanitize_filename(info.get("title", "video"))
        if audio_only:
            ext = audio_format.lower()
            display_name = f"{title_safe}.{ext}"
        else:
            ext = "mp4"
            display_name = f"{title_safe}.{ext}"

        tracker = ProgressTracker()
        progress_bar = st.progress(0.0, text="Starting download…")
        status_text = st.empty()

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Run the download in the current thread so we can update the
            # progress bar between yt-dlp progress hook calls.
            error_container: list[Exception] = []
            result_container: list[str] = []

            def _do_download() -> None:
                try:
                    path = download_media(
                        url=url,
                        fmt_selector=fmt_selector,
                        output_dir=tmp_dir,
                        audio_only=audio_only,
                        audio_format=audio_format if audio_only else "mp3",
                        tracker=tracker,
                    )
                    result_container.append(path)
                except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError, yt_dlp.utils.YoutubeDLError) as exc:
                    error_container.append(exc)
                except Exception as exc:  # noqa: BLE001 — catch-all for truly unexpected errors
                    error_container.append(exc)

            dl_thread = threading.Thread(target=_do_download, daemon=True)
            dl_thread.start()

            # Poll progress while the download thread is running
            while dl_thread.is_alive():
                pct = tracker.percent
                speed = tracker.speed
                eta = tracker.eta
                label = f"Downloading… {pct * 100:.1f}%"
                if speed:
                    label += f"  ·  {speed}"
                if eta:
                    label += f"  ·  ETA {eta}"
                progress_bar.progress(min(pct, 1.0), text=label)
                status_text.markdown(f"`{label}`")
                dl_thread.join(timeout=0.5)

            dl_thread.join()

            if error_container:
                exc = error_container[0]
                progress_bar.empty()
                status_text.empty()
                if "unavailable" in str(exc).lower() or "private" in str(exc).lower():
                    st.error("❌ This video is unavailable or private.")
                elif "format" in str(exc).lower():
                    st.error(
                        "❌ The selected format is not available for this video. "
                        "Try a different resolution."
                    )
                else:
                    st.error(f"❌ Download failed: {exc}")
                st.stop()

            if not result_container:
                st.error("❌ Download failed: no output file was produced.")
                st.stop()

            output_path = result_container[0]
            progress_bar.progress(1.0, text="✅ Download complete!")
            status_text.empty()

            # Read the file into memory so we can serve it via st.download_button
            with open(output_path, "rb") as fh:
                file_bytes = fh.read()

        # Determine MIME type
        mime_map = {
            "mp4": "video/mp4",
            "mp3": "audio/mpeg",
            "m4a": "audio/mp4",
            "webm": "audio/webm",
        }
        mime = mime_map.get(ext, "application/octet-stream")

        st.success(f"✅ Ready! Click below to save **{display_name}**.")
        st.download_button(
            label=f"💾 Save {display_name}",
            data=io.BytesIO(file_bytes),
            file_name=display_name,
            mime=mime,
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
