"""
DR Check - Output Formatters
Handles formatting and saving DR14 analysis results.
"""

import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from drcheck.analysis import DR14Result
from drcheck.__version__ import __version__

logger = logging.getLogger(__name__)


@dataclass
class TrackResult:
    """Result for a single track with metadata."""

    filename: str
    dr_value: int
    peak_db: float
    rms_db: float
    duration: float
    channel_dr: list[float]
    sample_rate: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    format_name: str | None = None

    @classmethod
    def from_dr14_result(
        cls,
        filepath: Path,
        result: DR14Result,
        duration: float,
        sample_rate: int | None = None,
        channels: int | None = None,
        bit_depth: int | None = None,
        format_name: str | None = None,
    ) -> "TrackResult":
        """Create TrackResult from DR14Result and file info."""
        return cls(
            filename=filepath.name,
            dr_value=result.dr14,
            peak_db=result.peak_db,
            rms_db=result.rms_db,
            duration=duration,
            channel_dr=result.channel_dr.tolist(),
            sample_rate=sample_rate,
            channels=channels,
            bit_depth=bit_depth,
            format_name=format_name,
        )


@dataclass
class AlbumResult:
    """Results for an album/collection of tracks."""

    tracks: list[TrackResult]
    album_dr: int
    directory: Path
    analyzed_at: datetime
    artist: str | None = None
    album: str | None = None

    @property
    def num_tracks(self) -> int:
        """Number of tracks in the album."""
        return len(self.tracks)

    @property
    def total_duration(self) -> float:
        """Total duration of all tracks in seconds."""
        return sum(t.duration for t in self.tracks)

    def __post_init__(self):
        """Calculate album DR if not provided."""
        if not self.tracks:
            self.album_dr = 0
        else:
            # Album DR is the mean of track DRs, rounded
            self.album_dr = round(
                sum(t.dr_value for t in self.tracks) / len(self.tracks)
            )


class Formatter(Protocol):
    """Protocol for output formatters."""

    def format_album(self, album: AlbumResult) -> str:
        """Format album results as a string."""
        ...

    def format_track(self, track: TrackResult) -> str:
        """Format single track result as a string."""
        ...


class TextTableFormatter:
    """Plain text table formatter (similar to original DR14 tool)."""

    def __init__(self, show_channels: bool = False):
        self.show_channels = show_channels

    def format_album(self, album: AlbumResult) -> str:
        """Format album results as plain text table."""
        lines = []

        # Header with tool info
        lines.append(f"DR Check - Dynamic Range Analyzer v{__version__}")
        lines.append(f"log date: {album.analyzed_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("-" * 80)

        # Use artist/album if available, otherwise fall back to directory
        if album.artist and album.album:
            analyzed_line = f"Analyzed: {album.artist} / {album.album}"
        else:
            analyzed_line = f"Analyzed: {album.directory}"

        lines.append(analyzed_line)
        lines.append("-" * 80)
        lines.append("")

        # Table header - adjust based on show_channels
        if self.show_channels and album.tracks and len(album.tracks[0].channel_dr) > 1:
            lines.append(
                f"{'DR':<6} {'Peak':<14} {'RMS':<14} {'Duration':<9} {'DR (L)':<8} {'DR (R)':<8} Track"
            )
        else:
            lines.append(f"{'DR':<6} {'Peak':<14} {'RMS':<14} {'Duration':<9} Track")

        lines.append("-" * 80)

        # Track rows
        for i, track in enumerate(album.tracks, 1):
            dr_str = f"DR{track.dr_value}"
            peak_str = f"{track.peak_db:.2f} dBFS"
            rms_str = f"{track.rms_db:.2f} dBFS"
            duration_str = self._format_duration(track.duration)

            # Remove file extension and add track number if not present
            filename = track.filename
            if not filename[:2].isdigit():
                filename = f"{i:02d}-{filename}"

            # Remove extension
            if "." in filename:
                filename = filename.rsplit(".", 1)[0]

            if self.show_channels and len(track.channel_dr) > 1:
                ch1_str = f"DR{track.channel_dr[0]:.2f}"
                ch2_str = f"DR{track.channel_dr[1]:.2f}"
                row = f"{dr_str:<6} {peak_str:<14} {rms_str:<14} {duration_str:<9} {ch1_str:<8} {ch2_str:<8} {filename}"
            else:
                row = f"{dr_str:<6} {peak_str:<14} {rms_str:<14} {duration_str:<9} {filename}"

            lines.append(row)

        lines.append("-" * 80)
        lines.append("")

        # Summary section
        lines.append(f"Number of tracks:  {album.num_tracks}")
        lines.append(f"Official DR value: DR{album.album_dr}")

        # Add technical info if available from first track
        if album.tracks:
            first_track = album.tracks[0]
            lines.append("")

            if first_track.sample_rate:
                lines.append(f"Samplerate:        {first_track.sample_rate} Hz")

            if first_track.channels:
                lines.append(f"Channels:          {first_track.channels}")

            if first_track.bit_depth:
                lines.append(f"Bits per sample:   {first_track.bit_depth}")

                # Calculate bitrate if we have the info
                if first_track.sample_rate and first_track.channels:
                    bitrate = (
                        first_track.sample_rate
                        * first_track.bit_depth
                        * first_track.channels
                    ) / 1000
                    lines.append(f"Bitrate:           {int(bitrate)} kbps")

            if first_track.format_name:
                lines.append(f"Codec:             {first_track.format_name}")

        lines.append("=" * 80)

        return "\n".join(lines)

    def format_track(self, track: TrackResult) -> str:
        """Format single track result."""
        lines = []
        lines.append(f"File: {track.filename}")
        lines.append(f"DR Value: DR{track.dr_value}")
        lines.append(f"Peak: {track.peak_db:.2f} dBFS")
        lines.append(f"RMS: {track.rms_db:.2f} dBFS")
        lines.append(f"Duration: {self._format_duration(track.duration)}")

        if self.show_channels and len(track.channel_dr) > 1:
            lines.append("Per-channel DR:")
            for i, dr in enumerate(track.channel_dr, 1):
                lines.append(f"  Channel {i}: DR{dr:.2f}")

        return "\n".join(lines)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration as M:SS or MM:SS."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"


class BBCodeFormatter:
    """BBCode formatter for forum posts."""

    def format_album(self, album: AlbumResult) -> str:
        """Format album results as BBCode."""
        lines = []

        lines.append("[b]DR Check - Dynamic Range Analyzer[/b]")
        lines.append("")

        # Use artist/album if available, otherwise fall back to directory
        if album.artist and album.album:
            lines.append(f"[b]Analyzed:[/b] {album.artist} / {album.album}")
        else:
            lines.append(f"[b]Directory:[/b] {album.directory}")

        lines.append(f"[b]Date:[/b] {album.analyzed_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"[b]Number of tracks:[/b] {album.num_tracks}")
        lines.append("")
        lines.append(f"[b]Album DR:[/b] DR{album.album_dr}")
        lines.append("")

        # Table using code block for alignment
        lines.append("[code]")
        lines.append(f"{'DR':<4} {'Peak':<10} {'RMS':<10} {'Duration':<10} Filename")
        lines.append("-" * 70)

        for track in album.tracks:
            dr_str = f"DR{track.dr_value}"
            peak_str = f"{track.peak_db:.2f} dB"
            rms_str = f"{track.rms_db:.2f} dB"
            duration_str = TextTableFormatter._format_duration(track.duration)

            # Remove extension from filename
            filename = track.filename
            if "." in filename:
                filename = filename.rsplit(".", 1)[0]

            row = f"{dr_str:<4} {peak_str:<10} {rms_str:<10} {duration_str:<10} {filename}"
            lines.append(row)

        lines.append("[/code]")

        return "\n".join(lines)

    def format_track(self, track: TrackResult) -> str:
        """Format single track result as BBCode."""
        lines = []
        lines.append("[b]File:[/b] " + track.filename)
        lines.append("[b]DR Value:[/b] DR" + str(track.dr_value))
        lines.append(f"[b]Peak:[/b] {track.peak_db:.2f} dB")
        lines.append(f"[b]RMS:[/b] {track.rms_db:.2f} dB")
        return "\n".join(lines)


class CSVFormatter:
    """CSV formatter for spreadsheet import."""

    def format_album(self, album: AlbumResult) -> str:
        """Format album results as CSV."""
        lines = []

        # Header
        lines.append("Filename,DR,Peak (dB),RMS (dB),Duration (s)")

        # Data rows
        for track in album.tracks:
            row = f"{track.filename},{track.dr_value},{track.peak_db:.2f},{track.rms_db:.2f},{track.duration:.2f}"
            lines.append(row)

        # Summary row
        lines.append("")
        lines.append(f"Album DR,{album.album_dr}")
        lines.append(f"Total Tracks,{album.num_tracks}")
        lines.append(f"Total Duration,{album.total_duration:.2f}")

        return "\n".join(lines)

    def format_track(self, track: TrackResult) -> str:
        """Format single track as CSV."""
        return f"{track.filename},{track.dr_value},{track.peak_db:.2f},{track.rms_db:.2f},{track.duration:.2f}"


def save_results(
    album: AlbumResult,
    output_dir: Path | None = None,
    format_type: str = "text",
    filename: str = "dr.txt",
    show_channels: bool = False,
    audio_files: list[Path] | None = None,
) -> Path:
    """
    Save album results to a file.

    Args:
        album: Album results to save
        output_dir: Directory to save to (defaults to album directory)
        format_type: Output format ("text", "bbcode", "csv", "html")
        filename: Output filename
        show_channels: Show per-channel DR values
        audio_files: List of audio file paths (for HTML album art extraction)

    Returns:
        Path to saved file

    Raises:
        ValueError: If format_type is not supported
    """
    if output_dir is None:
        output_dir = album.directory

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Select formatter
    formatters = {
        "text": TextTableFormatter(show_channels=show_channels),
        "bbcode": BBCodeFormatter(),
        "csv": CSVFormatter(),
        "html": HTMLFormatter(show_channels=show_channels),
    }

    if format_type not in formatters:
        raise ValueError(
            f"Unsupported format: {format_type}. Choose from: {', '.join(formatters.keys())}"
        )

    formatter = formatters[format_type]

    # Adjust filename extension based on format
    if format_type == "csv" and not filename.endswith(".csv"):
        filename = Path(filename).stem + ".csv"
    elif format_type == "html" and not filename.endswith(".html"):
        filename = Path(filename).stem + ".html"

    output_path = output_dir / filename

    # Format and save
    if format_type == "html":
        content = formatter.format_album(album, audio_files=audio_files)
    else:
        content = formatter.format_album(album)

    output_path.write_text(content, encoding="utf-8")

    logger.info(f"Results saved to: {output_path}")

    return output_path


def print_results(
    album: AlbumResult | None = None,
    track: TrackResult | None = None,
    format_type: str = "text",
    show_channels: bool = False,
) -> None:
    """
    Print results to stdout.

    Args:
        album: Album results to print (if analyzing multiple files)
        track: Single track result to print
        format_type: Output format ("text", "bbcode")
        show_channels: Whether to show per-channel DR values
    """
    if album:
        if format_type == "bbcode":
            formatter = BBCodeFormatter()
        else:
            formatter = TextTableFormatter(show_channels=show_channels)

        print(formatter.format_album(album))

    elif track:
        if format_type == "bbcode":
            formatter = BBCodeFormatter()
        else:
            formatter = TextTableFormatter(show_channels=show_channels)

        print(formatter.format_track(track))

    else:
        logger.warning("No results to print")


def extract_album_art(audio_files: list[Path]) -> str | None:
    """
    Extract album art from audio files or find cover image in directory.

    Args:
        audio_files: List of audio file paths to check

    Returns:
        Base64-encoded image data or None if no art found
    """
    if not audio_files:
        return None

    # First, try to find cover image files in the directory
    directory = audio_files[0].parent
    cover_names = [
        "cover.jpg",
        "cover.png",
        "folder.jpg",
        "folder.png",
        "album.jpg",
        "album.png",
        "front.jpg",
        "front.png",
    ]

    for cover_name in cover_names:
        cover_path = directory / cover_name
        if cover_path.exists():
            try:
                image_data = cover_path.read_bytes()
                b64_data = base64.b64encode(image_data).decode("utf-8")
                ext = cover_path.suffix.lower()
                mime_type = "image/jpeg" if ext == ".jpg" else "image/png"
                logger.info(f"Found album art: {cover_path.name}")
                return f"data:{mime_type};base64,{b64_data}"
            except Exception as e:
                logger.debug(f"Could not read cover image {cover_path}: {e}")

    # Try to extract from audio file metadata using mutagen
    try:
        from mutagen._file import File as MutagenFile
        from mutagen.flac import FLAC  # type: ignore
        from mutagen.id3._frames import APIC  # type: ignore
        from mutagen.mp3 import MP3  # type: ignore

        for audio_file in audio_files[:1]:  # Check only first file (already checked folder)
            try:
                audio = MutagenFile(audio_file)

                if audio is None:
                    continue

                # Handle FLAC files
                if isinstance(audio, FLAC):
                    if hasattr(audio, "pictures") and audio.pictures:
                        picture = audio.pictures[0]
                        b64_data = base64.b64encode(picture.data).decode("utf-8")
                        mime_type = getattr(picture, "mime", "image/jpeg")
                        logger.info(f"Extracted album art from {audio_file.name}")
                        return f"data:{mime_type};base64,{b64_data}"

                # Handle MP3 files
                elif isinstance(audio, MP3):
                    if hasattr(audio, "tags") and audio.tags is not None:
                        for tag in audio.tags.values():  # type: ignore
                            if isinstance(tag, APIC):
                                b64_data = base64.b64encode(tag.data).decode("utf-8")  # type: ignore
                                mime_type = getattr(tag, "mime", "image/jpeg")
                                logger.info(
                                    f"Extracted album art from {audio_file.name}"
                                )
                                return f"data:{mime_type};base64,{b64_data}"

                # Handle other formats with pictures tag
                elif hasattr(audio, "pictures") and audio.pictures:
                    picture = audio.pictures[0]
                    b64_data = base64.b64encode(picture.data).decode("utf-8")
                    mime_type = getattr(picture, "mime", "image/jpeg")
                    logger.info(f"Extracted album art from {audio_file.name}")
                    return f"data:{mime_type};base64,{b64_data}"

            except Exception as e:
                logger.debug(f"Could not extract art from {audio_file}: {e}")
                continue

    except ImportError:
        logger.debug("mutagen not available for album art extraction")

    logger.debug("No album art found")
    return None


class HTMLFormatter:
    """HTML formatter with modern styling and album art."""

    def __init__(self, show_channels: bool = False, include_album_art: bool = True):
        self.show_channels = show_channels
        self.include_album_art = include_album_art

    def format_album(
        self, album: AlbumResult, audio_files: list[Path] | None = None
    ) -> str:
        """
        Format album results as HTML.

        Args:
            album: Album results to format
            audio_files: List of audio file paths (for album art extraction)

        Returns:
            Complete HTML document as string
        """
        # Extract album art if requested and files provided
        album_art_data = None
        if self.include_album_art and audio_files:
            album_art_data = extract_album_art(audio_files)

        # Build HTML
        html_parts = []
        html_parts.append(self._get_html_header())
        html_parts.append(self._get_css())
        html_parts.append("</head><body>")
        html_parts.append(self._get_report_header(album, album_art_data))
        html_parts.append(self._get_tracks_table(album))
        html_parts.append(self._get_summary_section(album))
        html_parts.append(self._get_footer())
        html_parts.append("</body></html>")

        return "\n".join(html_parts)

    def _get_html_header(self) -> str:
        """Get HTML header and meta tags."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="generator" content="DR Check v{__version__}">
    <title>Dynamic Range Analysis Report</title>"""

    def _get_css(self) -> str:
        """Get embedded CSS styles."""
        return """
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: white;
            padding: 40px;
            display: flex;
            gap: 30px;
            align-items: center;
        }
        .album-art {
            width: 200px;
            height: 200px;
            border-radius: 8px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            object-fit: cover;
            flex-shrink: 0;
        }
        .album-art-placeholder {
            width: 200px;
            height: 200px;
            border-radius: 8px;
            background: rgba(255,255,255,0.1);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 60px;
            flex-shrink: 0;
        }
        .header-info { flex: 1; }
        .header h1 { font-size: 2em; margin-bottom: 10px; font-weight: 600; }
        .header .subtitle { font-size: 1.2em; opacity: 0.9; margin-bottom: 20px; }
        .header .meta { display: flex; gap: 30px; flex-wrap: wrap; }
        .header .meta-item { display: flex; flex-direction: column; gap: 5px; }
        .header .meta-label {
            font-size: 0.85em;
            opacity: 0.8;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .header .meta-value { font-size: 1.5em; font-weight: 700; }
        .dr-badge {
            display: inline-block;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 1.2em;
        }
        .dr-high { background: #10b981; color: white; }
        .dr-medium { background: #f59e0b; color: white; }
        .dr-low { background: #ef4444; color: white; }
        .content { padding: 40px; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        thead {
            background: #f8fafc;
            position: sticky;
            top: 0;
        }
        th {
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #475569;
            border-bottom: 2px solid #e2e8f0;
        }
        td {
            padding: 12px;
            border-bottom: 1px solid #e2e8f0;
        }
        tbody tr:hover { background: #f8fafc; }
        .track-number { color: #94a3b8; font-weight: 500; }
        .track-name { font-weight: 500; color: #1e293b; }
        .dr-value { font-weight: 700; font-size: 1.1em; }
        .summary {
            background: #f8fafc;
            padding: 30px;
            border-radius: 8px;
            margin-top: 30px;
        }
        .summary h2 { color: #1e293b; margin-bottom: 20px; }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }
        .summary-item {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .summary-label {
            font-size: 0.85em;
            color: #64748b;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .summary-value { font-size: 1.5em; font-weight: 700; color: #1e293b; }
        .footer {
            text-align: center;
            padding: 30px;
            color: #94a3b8;
            font-size: 0.9em;
            border-top: 1px solid #e2e8f0;
        }
        @media (max-width: 768px) {
            .header { flex-direction: column; text-align: center; }
            .album-art, .album-art-placeholder { width: 150px; height: 150px; }
            table { font-size: 0.9em; }
            th, td { padding: 8px; }
        }
    </style>"""

    def _get_report_header(self, album: AlbumResult, album_art_data: str | None) -> str:
        """Generate report header with album info and art."""
        if album.artist and album.album:
            title = f"{album.artist}"
            subtitle = album.album
        else:
            title = "Dynamic Range Analysis"
            subtitle = str(album.directory)

        dr = album.album_dr
        dr_class = "dr-high" if dr >= 14 else "dr-medium" if dr >= 8 else "dr-low"

        if album_art_data:
            art_html = f'<img src="{album_art_data}" alt="Album Art" class="album-art">'
        else:
            art_html = '<div class="album-art-placeholder">🎵</div>'

        return f"""
    <div class="container">
        <div class="header">
            {art_html}
            <div class="header-info">
                <h1>{title}</h1>
                <div class="subtitle">{subtitle}</div>
                <div class="meta">
                    <div class="meta-item">
                        <div class="meta-label">Album DR</div>
                        <div class="meta-value"><span class="dr-badge {dr_class}">DR{dr}</span></div>
                    </div>
                    <div class="meta-item">
                        <div class="meta-label">Tracks</div>
                        <div class="meta-value">{album.num_tracks}</div>
                    </div>
                    <div class="meta-item">
                        <div class="meta-label">Analyzed</div>
                        <div class="meta-value">{album.analyzed_at.strftime("%Y-%m-%d")}</div>
                    </div>
                </div>
            </div>
        </div>
        <div class="content">"""

    def _get_tracks_table(self, album: AlbumResult) -> str:
        """Generate tracks table."""
        headers = ["#", "Track", "DR", "Peak (dB)", "RMS (dB)", "Duration"]

        if self.show_channels and album.tracks and len(album.tracks[0].channel_dr) > 1:
            headers.extend(["DR (L)", "DR (R)"])

        html = "<table><thead><tr>"
        for header in headers:
            html += f"<th>{header}</th>"
        html += "</tr></thead>\n<tbody>"

        for i, track in enumerate(album.tracks, 1):
            filename = (
                track.filename.rsplit(".", 1)[0]
                if "." in track.filename
                else track.filename
            )
            duration = self._format_duration(track.duration)

            dr = track.dr_value
            dr_color = "#10b981" if dr >= 14 else "#f59e0b" if dr >= 8 else "#ef4444"

            html += f"""
                <tr>
                    <td class="track-number">{i}</td>
                    <td class="track-name">{filename}</td>
                    <td class="dr-value" style="color: {dr_color}">DR{dr}</td>
                    <td>{track.peak_db:.2f}</td>
                    <td>{track.rms_db:.2f}</td>
                    <td>{duration}</td>"""

            if self.show_channels and len(track.channel_dr) > 1:
                html += f"<td>DR{track.channel_dr[0]:.2f}</td><td>DR{track.channel_dr[1]:.2f}</td>"

            html += "</tr>"

        html += "</tbody></table>"
        return html

    def _get_summary_section(self, album: AlbumResult) -> str:
        """Generate technical summary section."""
        html = '<div class="summary"><h2>Technical Information</h2><div class="summary-grid">'

        if album.tracks:
            track = album.tracks[0]

            if track.sample_rate:
                html += f"""<div class="summary-item">
                    <div class="summary-label">Sample Rate</div>
                    <div class="summary-value">{track.sample_rate:,} Hz</div>
                </div>"""

            if track.channels:
                html += f"""<div class="summary-item">
                    <div class="summary-label">Channels</div>
                    <div class="summary-value">{track.channels}</div>
                </div>"""

            if track.bit_depth:
                html += f"""<div class="summary-item">
                    <div class="summary-label">Bit Depth</div>
                    <div class="summary-value">{track.bit_depth}-bit</div>
                </div>"""

            if track.format_name:
                html += f"""<div class="summary-item">
                    <div class="summary-label">Format</div>
                    <div class="summary-value">{track.format_name}</div>
                </div>"""

        total_mins = int(album.total_duration // 60)
        total_secs = int(album.total_duration % 60)
        html += f"""<div class="summary-item">
                <div class="summary-label">Total Duration</div>
                <div class="summary-value">{total_mins}:{total_secs:02d}</div>
            </div></div></div>"""

        return html

    def _get_footer(self) -> str:
        """Generate page footer."""
        return f"""<div class="footer">
            Generated by DR Check v{__version__} - Dynamic Range Analyzer | Visit <a href="https://github.com/nixternal/drcheck" style="color: #667eea;">github.com/nixternal/drcheck</a>
        </div>
    </div>"""

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration as M:SS."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"
