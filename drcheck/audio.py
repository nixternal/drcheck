"""
DR Check - Audio File Reading
Handles reading and decoding various audio formats.
"""

import logging
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


def _read_tags(filepath: Path) -> tuple[str | None, str | None]:
    """
    Read artist and album tags from audio file.

    Args:
        filepath: Path to audio file

    Returns:
        Tuple of (artist, album) or (None, None) if tags cannot be read
    """
    try:
        from mutagen._file import File

        audio = File(filepath, easy=True)

        if audio is None:
            return None, None

        # Try to get artist and album tags
        # Different formats use different tag names, but mutagen.File(easy=True) normalizes them
        artist = None
        album = None

        if hasattr(audio, "tags") and audio.tags:
            # Easy tags interface (works for most formats)
            artist_tags = audio.tags.get("artist", []) or audio.tags.get(
                "albumartist", []
            )
            album_tags = audio.tags.get("album", [])

            if artist_tags:
                artist = (
                    artist_tags[0]
                    if isinstance(artist_tags, list)
                    else str(artist_tags)
                )
            if album_tags:
                album = (
                    album_tags[0] if isinstance(album_tags, list) else str(album_tags)
                )

        return artist, album

    except Exception as e:
        logger.debug(f"Could not read tags from {filepath}: {e}")
        return None, None


@dataclass
class AudioData:
    """Container for decoded audio data and metadata."""

    samples: NDArray[np.float32] | None  # Audio samples, shape (samples, channels)
    sample_rate: int
    channels: int
    duration_seconds: float
    filepath: Path
    bit_depth: int | None = None  # Bits per sample (16, 24, 32, etc.)
    format_name: str | None = None  # Format/codec name (FLAC, WAV, etc.)
    artist: str | None = None  # Artist tag
    album: str | None = None  # Album tag

    @property
    def is_mono(self) -> bool:
        """Check if audio is mono."""
        return self.channels == 1

    @property
    def is_stereo(self) -> bool:
        """Check if audio is stereo."""
        return self.channels == 2

    @property
    def bitrate_kbps(self) -> float | None:
        """Calculate approximate bitrate in kbps."""
        if self.bit_depth and self.duration_seconds > 0:
            # Bitrate = sample_rate * bit_depth * channels / 1000
            return (self.sample_rate * self.bit_depth * self.channels) / 1000
        return None

    def __str__(self) -> str:
        return (
            f"{self.filepath.name}: "
            f"{self.sample_rate}Hz, "
            f"{self.channels}ch, "
            f"{self.duration_seconds:.2f}s"
        )


class AudioReadError(Exception):
    """Raised when audio file cannot be read or decoded."""

    pass


class UnsupportedFormatError(AudioReadError):
    """Raised when audio format is not supported."""

    pass


def read_audio_file(filepath: Path | str) -> AudioData:
    """
    Read an audio file and return decoded audio data.

    Supports formats: FLAC, WAV, OGG, MP3, M4A, AIFF, and others
    supported by libsndfile.

    Args:
        filepath: Path to audio file

    Returns:
        AudioData object containing samples and metadata

    Raises:
        AudioReadError: If file cannot be read or is corrupted
        UnsupportedFormatError: If file format is not supported
        FileNotFoundError: If file does not exist
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"Audio file not found: {filepath}")

    if not filepath.is_file():
        raise AudioReadError(f"Path is not a file: {filepath}")

    logger.debug(f"Reading audio file: {filepath}")

    # Get format name from extension
    format_name = filepath.suffix.upper().lstrip(".")
    bit_depth = None

    # Read metadata tags
    artist, album = _read_tags(filepath)

    try:
        # Read audio file using soundfile (libsndfile backend)
        # This handles FLAC, WAV, OGG, and many others natively
        samples, sample_rate = sf.read(filepath, dtype="float32", always_2d=True)

        # Try to get bit depth from file info
        try:
            info = sf.info(filepath)
            # Map soundfile subtypes to bit depths
            subtype_map = {
                "PCM_16": 16,
                "PCM_24": 24,
                "PCM_32": 32,
                "FLOAT": 32,
                "DOUBLE": 64,
            }
            bit_depth = subtype_map.get(info.subtype, None)

            # Get more accurate format name if available
            if hasattr(info, "format"):
                format_name = info.format
        except Exception:
            pass  # bit_depth remains None if we can't determine it

    except sf.LibsndfileError as e:
        # libsndfile couldn't read it - might be MP3 or M4A
        logger.debug(f"libsndfile failed, trying alternative decoder: {e}")
        samples, sample_rate, bit_depth_fallback = _read_with_fallback(filepath)
        if bit_depth is None:
            bit_depth = bit_depth_fallback

    except Exception as e:
        raise AudioReadError(f"Failed to read audio file {filepath}: {e}") from e

    channels = samples.shape[1]
    duration = len(samples) / sample_rate

    logger.info(
        f"Loaded: {filepath.name} - {sample_rate}Hz, {channels}ch, {duration:.2f}s"
    )

    return AudioData(
        samples=samples,
        sample_rate=sample_rate,
        channels=channels,
        duration_seconds=duration,
        filepath=filepath,
        bit_depth=bit_depth,
        format_name=format_name,
        artist=artist,
        album=album,
    )


def _read_with_fallback(filepath: Path) -> tuple[NDArray[np.floating], int, int | None]:
    """
    Fallback reader for formats not supported by libsndfile (MP3, M4A).

    Uses pydub with ffmpeg backend for decoding.

    Args:
        filepath: Path to audio file

    Returns:
        Tuple of (samples, sample_rate, bit_depth)

    Raises:
        UnsupportedFormatError: If format cannot be decoded
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        raise UnsupportedFormatError(
            f"Cannot read {filepath.suffix} files. "
            "Install pydub and ffmpeg: pip install pydub"
        )

    try:
        # Load with pydub (uses ffmpeg)
        audio = AudioSegment.from_file(str(filepath))

        # Convert to numpy array
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)

        # Get bit depth
        bit_depth = audio.sample_width * 8

        # Normalize to [-1.0, 1.0] range
        max_val = 2 ** (audio.sample_width * 8 - 1)
        samples = samples / max_val

        # Reshape for multi-channel
        if audio.channels > 1:
            samples = samples.reshape((-1, audio.channels))
        else:
            samples = samples.reshape((-1, 1))

        sample_rate = audio.frame_rate

        logger.debug(f"Decoded with pydub/ffmpeg: {filepath.name}")
        return samples, sample_rate, bit_depth

    except Exception as e:
        raise UnsupportedFormatError(f"Cannot decode {filepath}: {e}") from e


def get_supported_extensions() -> set[str]:
    """
    Get set of supported audio file extensions.

    Returns:
        Set of lowercase file extensions (including the dot)
    """
    # Core formats supported by libsndfile
    core_formats = {".flac", ".wav", ".aiff", ".aif", ".aifc", ".ogg", ".oga", ".opus"}

    # Formats requiring pydub/ffmpeg
    extended_formats = {".mp3", ".m4a", ".mp4", ".aac", ".wma"}

    if find_spec("pydub") is not None:
        return core_formats | extended_formats
    else:
        logger.debug("pydub not available, extended formats disabled")
        return core_formats


def is_supported_file(filepath: Path | str) -> bool:
    """
    Check if file extension is supported.

    Args:
        filepath: Path to check

    Returns:
        True if extension is supported
    """
    filepath = Path(filepath)
    return filepath.suffix.lower() in get_supported_extensions()


def find_audio_files(directory: Path | str, recursive: bool = False) -> list[Path]:
    """
    Find all supported audio files in a directory.

    Args:
        directory: Directory to search
        recursive: If True, search subdirectories recursively

    Returns:
        List of audio file paths, sorted alphabetically
    """
    directory = Path(directory)

    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    supported_exts = get_supported_extensions()

    # Choose glob pattern based on recursion
    pattern = "**/*" if recursive else "*"

    audio_files = [
        f
        for f in directory.glob(pattern)
        if f.is_file() and f.suffix.lower() in supported_exts
    ]

    logger.info(
        f"Found {len(audio_files)} audio files in {directory}"
        + (" (recursive)" if recursive else "")
    )

    return sorted(audio_files)
