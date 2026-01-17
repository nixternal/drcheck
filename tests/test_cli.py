"""
CLI tests that require actual audio files.
Add these to tests/test_cli.py to replace the skipped tests.
"""

import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from click.testing import CliRunner

from drcheck.__version__ import __version__
from drcheck.cli import cli

# ==============================================================================
# FIXTURES - Create real audio files for testing
# ==============================================================================


@pytest.fixture
def temp_audio_dir():
    """Create temporary directory for audio file tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_test_wav(
    filepath: Path, duration: float = 10.0, sample_rate: int = 44100, channels: int = 2
):
    """
    Create a valid WAV file for testing.

    Args:
        filepath: Path where to save the WAV file
        duration: Duration in seconds
        sample_rate: Sample rate in Hz
        channels: Number of channels (1=mono, 2=stereo)
    """
    num_samples = int(sample_rate * duration)
    t = np.linspace(0, duration, num_samples)

    # Create simple sine wave
    audio = np.sin(2 * np.pi * 440 * t) * 0.5

    if channels == 2:
        audio = np.column_stack([audio, audio * 0.8])
    else:
        audio = audio.reshape(-1, 1)

    sf.write(filepath, audio, sample_rate, subtype="PCM_16")


@pytest.fixture
def valid_audio_files(temp_audio_dir):
    """Create multiple valid audio files for testing."""
    files = []
    for i in range(3):
        filepath = temp_audio_dir / f"track_{i + 1:02d}.wav"
        create_test_wav(filepath, duration=10.0)
        files.append(filepath)
    return files


@pytest.fixture
def mixed_files(temp_audio_dir):
    """Create a mix of valid and invalid files for testing."""
    files = {"valid": [], "invalid": [], "all": []}

    # Create 3 valid audio files
    for i in range(3):
        filepath = temp_audio_dir / f"good_track_{i + 1:02d}.wav"
        create_test_wav(filepath, duration=10.0)
        files["valid"].append(filepath)
        files["all"].append(filepath)

    # Create 2 corrupted files
    for i in range(2):
        filepath = temp_audio_dir / f"bad_track_{i + 1:02d}.flac"
        filepath.write_bytes(b"FAKE CORRUPTED FLAC DATA")
        files["invalid"].append(filepath)
        files["all"].append(filepath)

    return files


class TestCLIErrorMessages:
    """Integration tests for CLI error message display."""

    def test_partial_success_exit_code(self, mixed_files):
        """Test that partial success doesn't exit with error code."""
        runner = CliRunner()

        # Analyze directory with mixed valid/invalid files
        result = runner.invoke(cli, ["analyze", str(mixed_files["all"][0].parent)])

        # Should process successfully (exit code 0) despite some failures
        # because some files succeeded
        assert result.exit_code == 0, "Partial success should exit with code 0"

        # Should show success count
        assert "Successfully processed" in result.output or "✅" in result.output

        # Should show warning about failures
        assert "error(s)" in result.output.lower() or "failed" in result.output.lower()

        # Should show both successful and failed counts
        output_lower = result.output.lower()
        assert "3" in result.output  # 3 successful files
        assert "2" in result.output  # 2 failed files

    def test_complete_failure_exit_code(self, temp_audio_dir):
        """Test that complete failure exits with error code 1."""
        runner = CliRunner()

        # Create only invalid files
        fake_file = temp_audio_dir / "fake.flac"
        fake_file.write_bytes(b"not a real flac file")

        result = runner.invoke(cli, ["analyze", str(temp_audio_dir)])

        # Should exit with error code since all files failed
        assert result.exit_code == 1, "Complete failure should exit with code 1"

        # Should show no successful files
        assert (
            "No files were successfully processed" in result.output
            or result.output.count("✅") == 0
        )


class TestSuccessMessages:
    """Tests for success message improvements."""

    def test_success_message_shown(self, valid_audio_files):
        """Test that success message is shown when all files succeed."""
        runner = CliRunner()

        # Analyze directory with only valid files
        result = runner.invoke(cli, ["analyze", str(valid_audio_files[0].parent)])

        # Should succeed
        assert result.exit_code == 0, "All valid files should result in exit code 0"

        # Should show success message
        assert "Successfully analyzed" in result.output or "✅" in result.output

        # Should mention number of files processed
        assert "3" in result.output

        # Should NOT show error messages
        assert "Failed to process" not in result.output
        assert "❌" not in result.output

    def test_success_rate_calculation(self, mixed_files):
        """Test that success rate percentage is calculated correctly."""
        runner = CliRunner()

        # Analyze directory with mixed files (3 valid, 2 invalid)
        result = runner.invoke(cli, ["analyze", str(mixed_files["all"][0].parent)])

        # Should calculate and show success rate
        # 3 out of 5 = 60%
        assert "3/5" in result.output or "3 of 5" in result.output

        # Should show percentage (might be formatted as 60.0% or 60%)
        assert "60" in result.output

        # Should show the actual successful count
        assert (
            "Successfully processed: 3" in result.output
            or "3 file(s) processed successfully" in result.output
        )


class TestProgressDisplay:
    """Tests for improved progress display."""

    def test_progress_shows_percentage(self, valid_audio_files):
        """Test that progress display includes percentage."""
        runner = CliRunner()

        result = runner.invoke(cli, ["analyze", str(valid_audio_files[0].parent)])

        # Should show percentage in progress (e.g., "33.3%", "66.7%", "100.0%")
        assert "%" in result.output

        # Should show completion like "[1/3", "[2/3", "[3/3"
        assert "[1/3" in result.output or "1/3" in result.output
        assert "[3/3" in result.output or "3/3" in result.output

    def test_progress_shows_checkmarks(self, valid_audio_files):
        """Test that progress shows ✅/❌ symbols."""
        runner = CliRunner()

        result = runner.invoke(cli, ["analyze", str(valid_audio_files[0].parent)])

        # Should show success checkmarks
        assert "✅" in result.output

        # Count should match number of files
        checkmark_count = result.output.count("✅")
        assert checkmark_count >= 3, f"Expected 3+ checkmarks, got {checkmark_count}"

    def test_progress_mixed_success_failure(self, mixed_files):
        """Test progress display with both successes and failures."""
        runner = CliRunner()

        result = runner.invoke(cli, ["analyze", str(mixed_files["all"][0].parent)])

        # Should show both success and failure symbols
        assert "✅" in result.output, "Should show success checkmarks"
        assert "❌" in result.output, "Should show failure crosses"

        # Count checkmarks in progress lines only (lines with percentage)
        # This excludes the final success message checkmark
        progress_lines = [line for line in result.output.split("\n") if "%]" in line]
        success_in_progress = sum(line.count("✅") for line in progress_lines)
        failure_in_progress = sum(line.count("❌") for line in progress_lines)

        assert success_in_progress == 3, (
            f"Expected 3 successes in progress, got {success_in_progress}"
        )
        assert failure_in_progress == 2, (
            f"Expected 2 failures in progress, got {failure_in_progress}"
        )


class TestDetailedOutput:
    """Tests for detailed DR output during processing."""

    def test_shows_dr_values_during_processing(self, valid_audio_files):
        """Test that DR values are displayed for each file."""
        runner = CliRunner()

        result = runner.invoke(cli, ["analyze", str(valid_audio_files[0].parent)])

        # Should show DR values in output
        assert "DR" in result.output

        # Should show peak and RMS values
        assert "Peak:" in result.output or "dB" in result.output
        assert "RMS:" in result.output or "dBFS" in result.output

    def test_channel_display(self, temp_audio_dir):
        """Test per-channel DR display with --show-channels flag."""
        # Create a stereo file
        stereo_file = temp_audio_dir / "stereo.wav"
        create_test_wav(stereo_file, duration=10.0, channels=2)

        runner = CliRunner()

        result = runner.invoke(cli, ["analyze", str(stereo_file), "--show-channels"])

        # Should show channel-specific DR values
        assert "Ch1:" in result.output or "DR (L)" in result.output
        assert "Ch2:" in result.output or "DR (R)" in result.output


class TestSaveResults:
    """Tests for saving results to files."""

    def test_save_results_creates_file(self, valid_audio_files, temp_audio_dir):
        """Test that --save creates output file."""
        runner = CliRunner()

        output_dir = temp_audio_dir / "output"

        result = runner.invoke(
            cli,
            [
                "analyze",
                str(valid_audio_files[0].parent),
                "--save",
                "--output",
                str(output_dir),
            ],
        )

        # Should succeed
        assert result.exit_code == 0

        # Should create output file
        assert output_dir.exists()
        output_files = list(output_dir.glob("dr.*"))
        assert len(output_files) > 0, "Should create at least one output file"

        # Should mention saved file in output
        assert "saved to" in result.output.lower() or "✅" in result.output

    def test_save_different_formats(self, valid_audio_files, temp_audio_dir):
        """Test saving in different formats."""
        runner = CliRunner()

        for format_type in ["text", "csv", "html"]:
            output_dir = temp_audio_dir / f"output_{format_type}"

            result = runner.invoke(
                cli,
                [
                    "analyze",
                    str(valid_audio_files[0].parent),
                    "--save",
                    "--format",
                    format_type,
                    "--output",
                    str(output_dir),
                ],
            )

            assert result.exit_code == 0, f"Failed for format {format_type}"

            # Check file was created with correct extension
            if format_type == "csv":
                assert (output_dir / "dr.csv").exists(), f"CSV file not created"
            elif format_type == "html":
                assert (output_dir / "dr.html").exists(), f"HTML file not created"
            else:
                assert (output_dir / "dr.txt").exists(), f"TXT file not created"


class TestVersionCommand:
    """Tests for version command."""

    def test_version_command(self):
        """Test that version command shows version info."""
        runner = CliRunner()
        result = runner.invoke(cli, ["version"])

        assert result.exit_code == 0
        assert __version__ in result.output
        assert "DR Check" in result.output
        assert "Python:" in result.output
        assert "Platform:" in result.output
        assert "Supported formats:" in result.output
        assert "github.com" in result.output

    def test_version_flag(self):
        """Test that --version flag still works."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert __version__ in result.output


# ==============================================================================
# Run instructions:
# ==============================================================================
# pytest tests/test_cli.py::TestCLIErrorMessages::test_partial_success_exit_code -v
# pytest tests/test_cli.py::TestSuccessMessages -v
# pytest tests/test_cli.py::TestProgressDisplay -v
# pytest tests/test_cli.py::TestDetailedOutput -v
# pytest tests/test_cli.py::TestSaveResults -v
# pytest tests/test_cli.py::TestVersionCommand -v
#
# Or run all:
# pytest tests/test_cli.py -v
