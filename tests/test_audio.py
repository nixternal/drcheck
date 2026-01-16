"""
Tests for audio file reading.

Note: These tests use synthetic audio files created on-the-fly.
For real file format testing, you'll need actual audio files.
"""

import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from drcheck.audio import (
    AudioData,
    AudioReadError,
    find_audio_files,
    get_supported_extensions,
    is_supported_file,
    read_audio_file,
)


@pytest.fixture
def temp_audio_dir():
    """Create a temporary directory for test audio files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_test_wav(
    filepath: Path, duration: float = 5.0, sample_rate: int = 44100, channels: int = 2
):
    """Create a test WAV file."""
    num_samples = int(sample_rate * duration)
    t = np.linspace(0, duration, num_samples)

    # Create simple sine wave
    audio = np.sin(2 * np.pi * 440 * t) * 0.5

    if channels == 2:
        audio = np.column_stack([audio, audio * 0.8])
    else:
        audio = audio.reshape(-1, 1)

    sf.write(filepath, audio, sample_rate, subtype="PCM_16")


def create_test_flac(
    filepath: Path, duration: float = 5.0, sample_rate: int = 44100, channels: int = 2
):
    """Create a test FLAC file."""
    num_samples = int(sample_rate * duration)
    t = np.linspace(0, duration, num_samples)

    # Create simple sine wave
    audio = np.sin(2 * np.pi * 440 * t) * 0.5

    if channels == 2:
        audio = np.column_stack([audio, audio * 0.8])
    else:
        audio = audio.reshape(-1, 1)

    sf.write(filepath, audio, sample_rate, subtype="PCM_24")


class TestAudioData:
    """Tests for AudioData dataclass."""

    def test_audio_data_properties(self, temp_audio_dir):
        """Test AudioData properties."""
        wav_file = temp_audio_dir / "test.wav"
        create_test_wav(wav_file, channels=1)

        audio_data = read_audio_file(wav_file)

        assert audio_data.is_mono
        assert not audio_data.is_stereo

    def test_stereo_audio_data(self, temp_audio_dir):
        """Test stereo AudioData."""
        wav_file = temp_audio_dir / "stereo.wav"
        create_test_wav(wav_file, channels=2)

        audio_data = read_audio_file(wav_file)

        assert audio_data.is_stereo
        assert not audio_data.is_mono

    def test_bitrate_calculation(self, temp_audio_dir):
        """Test bitrate calculation."""
        wav_file = temp_audio_dir / "test.wav"
        create_test_wav(wav_file)

        audio_data = read_audio_file(wav_file)

        if audio_data.bit_depth:
            expected_bitrate = (
                audio_data.sample_rate * audio_data.bit_depth * audio_data.channels
            ) / 1000
            assert audio_data.bitrate_kbps == pytest.approx(expected_bitrate)


class TestReadAudioFile:
    """Tests for reading audio files."""

    def test_read_wav_file(self, temp_audio_dir):
        """Test reading WAV file."""
        wav_file = temp_audio_dir / "test.wav"
        create_test_wav(wav_file, duration=10.0)

        audio_data = read_audio_file(wav_file)

        assert isinstance(audio_data, AudioData)
        assert audio_data.sample_rate == 44100
        assert audio_data.channels == 2
        assert 9.9 < audio_data.duration_seconds < 10.1  # Allow small tolerance
        assert audio_data.samples.shape[1] == 2  # Stereo
        assert audio_data.filepath == wav_file

    def test_read_flac_file(self, temp_audio_dir):
        """Test reading FLAC file."""
        flac_file = temp_audio_dir / "test.flac"
        create_test_flac(flac_file, duration=5.0)

        audio_data = read_audio_file(flac_file)

        assert isinstance(audio_data, AudioData)
        assert audio_data.sample_rate == 44100
        assert audio_data.channels == 2
        assert 4.9 < audio_data.duration_seconds < 5.1

    def test_read_mono_file(self, temp_audio_dir):
        """Test reading mono audio file."""
        wav_file = temp_audio_dir / "mono.wav"
        create_test_wav(wav_file, channels=1)

        audio_data = read_audio_file(wav_file)

        assert audio_data.channels == 1
        assert audio_data.samples.shape[1] == 1
        assert audio_data.is_mono

    def test_samples_in_correct_range(self, temp_audio_dir):
        """Test that samples are normalized to [-1.0, 1.0]."""
        wav_file = temp_audio_dir / "test.wav"
        create_test_wav(wav_file)

        audio_data = read_audio_file(wav_file)

        assert audio_data.samples.min() >= -1.0
        assert audio_data.samples.max() <= 1.0

    def test_samples_are_float32(self, temp_audio_dir):
        """Test that samples are returned as float32."""
        wav_file = temp_audio_dir / "test.wav"
        create_test_wav(wav_file)

        audio_data = read_audio_file(wav_file)

        assert audio_data.samples.dtype == np.float32

    def test_samples_are_2d(self, temp_audio_dir):
        """Test that samples are always 2D (even for mono)."""
        wav_file = temp_audio_dir / "mono.wav"
        create_test_wav(wav_file, channels=1)

        audio_data = read_audio_file(wav_file)

        assert audio_data.samples.ndim == 2
        assert audio_data.samples.shape[1] == 1

    def test_file_not_found(self):
        """Test that FileNotFoundError is raised for missing files."""
        with pytest.raises(FileNotFoundError):
            read_audio_file(Path("/nonexistent/file.wav"))

    def test_invalid_path_type(self, temp_audio_dir):
        """Test that error is raised for non-file paths."""
        with pytest.raises(AudioReadError, match="not a file"):
            read_audio_file(temp_audio_dir)  # Directory, not file

    def test_metadata_extraction(self, temp_audio_dir):
        """Test that metadata is extracted."""
        wav_file = temp_audio_dir / "test.wav"
        create_test_wav(wav_file)

        audio_data = read_audio_file(wav_file)

        # Should have bit depth (16 for PCM_16)
        assert audio_data.bit_depth == 16
        assert audio_data.format_name is not None

    def test_different_sample_rates(self, temp_audio_dir):
        """Test reading files with different sample rates."""
        for sample_rate in [44100, 48000, 96000]:
            wav_file = temp_audio_dir / f"test_{sample_rate}.wav"

            num_samples = int(sample_rate * 5.0)
            t = np.linspace(0, 5.0, num_samples)
            audio = (np.sin(2 * np.pi * 440 * t) * 0.5).reshape(-1, 1)
            sf.write(wav_file, audio, sample_rate)

            audio_data = read_audio_file(wav_file)
            assert audio_data.sample_rate == sample_rate


class TestSupportedFormats:
    """Tests for format support functions."""

    def test_get_supported_extensions(self):
        """Test getting supported extensions."""
        extensions = get_supported_extensions()

        assert isinstance(extensions, set)
        assert ".flac" in extensions
        assert ".wav" in extensions
        assert ".ogg" in extensions

        # All extensions should start with a dot
        assert all(ext.startswith(".") for ext in extensions)

        # All extensions should be lowercase
        assert all(ext == ext.lower() for ext in extensions)

    def test_is_supported_file(self):
        """Test checking if file is supported."""
        assert is_supported_file(Path("song.flac"))
        assert is_supported_file(Path("song.wav"))
        assert is_supported_file(Path("song.FLAC"))  # Case insensitive

        assert not is_supported_file(Path("song.txt"))
        assert not is_supported_file(Path("song.pdf"))
        assert not is_supported_file(Path("song.unknown"))


class TestFindAudioFiles:
    """Tests for finding audio files in directories."""

    def test_find_files_in_directory(self, temp_audio_dir):
        """Test finding audio files in a directory."""
        # Create some test files
        create_test_wav(temp_audio_dir / "song1.wav")
        create_test_wav(temp_audio_dir / "song2.wav")
        create_test_flac(temp_audio_dir / "song3.flac")

        # Create a non-audio file
        (temp_audio_dir / "readme.txt").write_text("hello")

        found_files = find_audio_files(temp_audio_dir)

        assert len(found_files) == 3
        assert all(f.is_file() for f in found_files)
        assert all(is_supported_file(f) for f in found_files)

    def test_find_files_recursive(self, temp_audio_dir):
        """Test recursive directory scanning."""
        # Create files in root
        create_test_wav(temp_audio_dir / "root.wav")

        # Create subdirectory with files
        subdir = temp_audio_dir / "subdir"
        subdir.mkdir()
        create_test_wav(subdir / "sub1.wav")
        create_test_flac(subdir / "sub2.flac")

        # Non-recursive should only find root file
        non_recursive = find_audio_files(temp_audio_dir, recursive=False)
        assert len(non_recursive) == 1

        # Recursive should find all files
        recursive = find_audio_files(temp_audio_dir, recursive=True)
        assert len(recursive) == 3

    def test_find_files_empty_directory(self, temp_audio_dir):
        """Test finding files in empty directory."""
        found_files = find_audio_files(temp_audio_dir)
        assert len(found_files) == 0

    def test_find_files_not_a_directory(self, temp_audio_dir):
        """Test that error is raised for non-directory."""
        file_path = temp_audio_dir / "file.txt"
        file_path.write_text("test")

        with pytest.raises(NotADirectoryError):
            find_audio_files(file_path)

    def test_find_files_sorted(self, temp_audio_dir):
        """Test that found files are sorted."""
        # Create files in non-alphabetical order
        create_test_wav(temp_audio_dir / "03-third.wav")
        create_test_wav(temp_audio_dir / "01-first.wav")
        create_test_wav(temp_audio_dir / "02-second.wav")

        found_files = find_audio_files(temp_audio_dir)

        # Should be sorted alphabetically
        assert found_files[0].name == "01-first.wav"
        assert found_files[1].name == "02-second.wav"
        assert found_files[2].name == "03-third.wav"

    def test_find_files_case_insensitive(self, temp_audio_dir):
        """Test that file extension matching is case insensitive."""
        create_test_wav(temp_audio_dir / "lowercase.wav")

        # Manually rename to uppercase extension
        uppercase_file = temp_audio_dir / "uppercase.WAV"
        create_test_wav(temp_audio_dir / "temp.wav")
        (temp_audio_dir / "temp.wav").rename(uppercase_file)

        found_files = find_audio_files(temp_audio_dir)

        assert len(found_files) == 2
        assert any(f.name == "uppercase.WAV" for f in found_files)


class TestAudioReadError:
    """Tests for audio reading errors."""

    def test_corrupted_file_handling(self, temp_audio_dir):
        """Test handling of corrupted audio files."""
        # Create a file that looks like audio but isn't
        fake_wav = temp_audio_dir / "fake.wav"
        fake_wav.write_bytes(b"not a real wav file")

        with pytest.raises(AudioReadError):
            read_audio_file(fake_wav)

    @pytest.mark.skip(reason="Difficult to test without specific environment setup")
    def test_unsupported_format_with_pydub_unavailable(self, temp_audio_dir):
        """Test that UnsupportedFormatError is raised for formats needing pydub."""
        pass
