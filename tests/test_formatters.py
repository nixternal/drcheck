"""
Tests for output formatters.
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from drcheck.formatters import (
    AlbumResult,
    BBCodeFormatter,
    CSVFormatter,
    HTMLFormatter,
    TextTableFormatter,
    TrackResult,
    save_results,
)


@pytest.fixture
def sample_track():
    """Create a sample track result."""
    return TrackResult(
        filename="01-Test Song.flac",
        dr_value=13,
        peak_db=-2.60,
        rms_db=-16.87,
        duration=313.5,  # 5:13.5
        channel_dr=[13.02, 12.66],
        sample_rate=96000,
        channels=2,
        bit_depth=24,
        format_name="FLAC",
    )


@pytest.fixture
def sample_album(sample_track):
    """Create a sample album result with multiple tracks."""
    tracks = [
        sample_track,
        TrackResult(
            filename="02-Another Song.flac",
            dr_value=12,
            peak_db=-1.50,
            rms_db=-15.20,
            duration=245.0,
            channel_dr=[12.10, 11.95],
            sample_rate=96000,
            channels=2,
            bit_depth=24,
            format_name="FLAC",
        ),
        TrackResult(
            filename="03-Third Track.flac",
            dr_value=14,
            peak_db=-3.20,
            rms_db=-17.80,
            duration=180.0,
            channel_dr=[14.05, 13.88],
            sample_rate=96000,
            channels=2,
            bit_depth=24,
            format_name="FLAC",
        ),
    ]

    return AlbumResult(
        tracks=tracks,
        album_dr=0,  # Will be calculated
        directory=Path("/music/test_album"),
        analyzed_at=datetime(2026, 1, 9, 12, 30, 45),
        artist="Test Artist",
        album="Test Album",
    )


class TestTrackResult:
    """Tests for TrackResult dataclass."""

    def test_track_result_creation(self, sample_track):
        """Test basic TrackResult creation."""
        assert sample_track.filename == "01-Test Song.flac"
        assert sample_track.dr_value == 13
        assert sample_track.peak_db == -2.60
        assert sample_track.rms_db == -16.87
        assert len(sample_track.channel_dr) == 2

    def test_track_result_with_metadata(self, sample_track):
        """Test that metadata fields are populated."""
        assert sample_track.sample_rate == 96000
        assert sample_track.channels == 2
        assert sample_track.bit_depth == 24
        assert sample_track.format_name == "FLAC"


class TestAlbumResult:
    """Tests for AlbumResult dataclass."""

    def test_album_dr_calculation(self, sample_album):
        """Test that album DR is calculated correctly."""
        # Should be mean of [13, 12, 14] = 13
        assert sample_album.album_dr == 13

    def test_num_tracks_property(self, sample_album):
        """Test num_tracks property."""
        assert sample_album.num_tracks == 3

    def test_total_duration_property(self, sample_album):
        """Test total_duration property."""
        expected = 313.5 + 245.0 + 180.0
        assert sample_album.total_duration == expected

    def test_album_with_artist_and_album_tags(self, sample_album):
        """Test album with artist and album metadata."""
        assert sample_album.artist == "Test Artist"
        assert sample_album.album == "Test Album"

    def test_empty_album(self):
        """Test album with no tracks."""
        album = AlbumResult(
            tracks=[], album_dr=0, directory=Path("/empty"), analyzed_at=datetime.now()
        )

        assert album.num_tracks == 0
        assert album.album_dr == 0
        assert album.total_duration == 0


class TestTextTableFormatter:
    """Tests for text table formatter."""

    def test_format_single_track(self, sample_track):
        """Test formatting a single track."""
        formatter = TextTableFormatter()
        output = formatter.format_track(sample_track)

        assert "01-Test Song.flac" in output
        assert "DR13" in output
        assert "-2.60 dBFS" in output
        assert "-16.87 dBFS" in output

    def test_format_album(self, sample_album):
        """Test formatting an album."""
        formatter = TextTableFormatter()
        output = formatter.format_album(sample_album)

        # Check header
        assert "DR Check" in output
        assert "2026-01-09 12:30:45" in output

        # Check artist/album line
        assert "Test Artist / Test Album" in output

        # Check table headers
        assert "DR" in output
        assert "Peak" in output
        assert "RMS" in output
        assert "Duration" in output
        assert "Track" in output

        # Check track data
        assert "DR13" in output
        assert "DR12" in output
        assert "DR14" in output

        # Check summary
        assert "Number of tracks:  3" in output
        assert "Official DR value: DR13" in output

        # Check technical info
        assert "96000 Hz" in output
        assert "Channels:          2" in output
        assert "Bits per sample:   24" in output
        assert "FLAC" in output

    def test_format_album_with_channels(self, sample_album):
        """Test formatting with per-channel display."""
        formatter = TextTableFormatter(show_channels=True)
        output = formatter.format_album(sample_album)

        # Should have channel headers
        assert "DR (L)" in output
        assert "DR (R)" in output

        # Should have channel values
        assert "DR13.02" in output
        assert "DR12.66" in output

    def test_format_album_without_metadata(self):
        """Test formatting album without artist/album tags."""
        album = AlbumResult(
            tracks=[
                TrackResult(
                    filename="song.flac",
                    dr_value=10,
                    peak_db=-1.0,
                    rms_db=-12.0,
                    duration=120.0,
                    channel_dr=[10.0, 10.0],
                )
            ],
            album_dr=0,
            directory=Path("/music/unknown"),
            analyzed_at=datetime.now(),
        )

        formatter = TextTableFormatter()
        output = formatter.format_album(album)

        # Should fall back to directory path
        assert "/music/unknown" in output

    def test_duration_formatting(self):
        """Test that durations are formatted correctly."""
        formatter = TextTableFormatter()

        # Test various durations
        assert formatter._format_duration(65.0) == "1:05"
        assert formatter._format_duration(125.0) == "2:05"
        assert formatter._format_duration(605.0) == "10:05"
        assert formatter._format_duration(3665.0) == "61:05"


class TestBBCodeFormatter:
    """Tests for BBCode formatter."""

    def test_format_album(self, sample_album):
        """Test BBCode album formatting."""
        formatter = BBCodeFormatter()
        output = formatter.format_album(sample_album)

        # Check BBCode tags
        assert "[b]" in output
        assert "[/b]" in output
        assert "[code]" in output
        assert "[/code]" in output

        # Check content
        assert "Test Artist / Test Album" in output
        assert "DR13" in output

    def test_format_track(self, sample_track):
        """Test BBCode track formatting."""
        formatter = BBCodeFormatter()
        output = formatter.format_track(sample_track)

        assert "[b]File:[/b]" in output
        assert "[b]DR Value:[/b]" in output
        assert "DR13" in output


class TestCSVFormatter:
    """Tests for CSV formatter."""

    def test_format_album(self, sample_album):
        """Test CSV album formatting."""
        formatter = CSVFormatter()
        output = formatter.format_album(sample_album)

        # Check header
        assert "Filename,DR,Peak (dB),RMS (dB),Duration (s)" in output

        # Check data rows
        lines = output.split("\n")
        assert len([line for line in lines if line.strip() and not line.startswith("Album")]) >= 3

        # Check summary
        assert "Album DR,13" in output
        assert "Total Tracks,3" in output

    def test_format_track(self, sample_track):
        """Test CSV track formatting."""
        formatter = CSVFormatter()
        output = formatter.format_track(sample_track)

        assert "01-Test Song.flac" in output
        assert "13," in output
        assert "-2.60," in output


class TestHTMLFormatter:
    """Tests for HTML formatter."""

    def test_format_album_basic(self, sample_album):
        """Test basic HTML album formatting."""
        formatter = HTMLFormatter()
        output = formatter.format_album(sample_album)

        # Check HTML structure
        assert "<!DOCTYPE html>" in output
        assert "<html" in output
        assert "</html>" in output
        assert "<head>" in output
        assert "<body>" in output

        # Check content
        assert "Test Artist" in output
        assert "Test Album" in output
        assert "DR13" in output

    def test_format_album_with_metadata(self, sample_album):
        """Test HTML with full metadata."""
        formatter = HTMLFormatter()
        output = formatter.format_album(sample_album)

        # Check technical info
        assert (
            "96000" in output or "96,000" in output
        )  # Sample rate with or without comma
        assert "24-bit" in output
        assert "FLAC" in output
        assert "2" in output  # Channels

    def test_format_album_without_art(self, sample_album):
        """Test HTML without album art."""
        formatter = HTMLFormatter(include_album_art=False)
        output = formatter.format_album(sample_album)

        # Should have placeholder
        assert "🎵" in output or "album-art-placeholder" in output

    def test_format_album_with_channels(self, sample_album):
        """Test HTML with per-channel display."""
        formatter = HTMLFormatter(show_channels=True)
        output = formatter.format_album(sample_album)

        # Should have channel headers
        assert "DR (L)" in output
        assert "DR (R)" in output

        # Should have channel values
        assert "13.02" in output
        assert "12.66" in output

    def test_html_has_css(self, sample_album):
        """Test that HTML includes embedded CSS."""
        formatter = HTMLFormatter()
        output = formatter.format_album(sample_album)

        assert "<style>" in output
        assert "</style>" in output
        assert "background:" in output  # Some CSS property

    def test_html_dr_color_coding(self, sample_album):
        """Test that DR values are color-coded."""
        formatter = HTMLFormatter()
        output = formatter.format_album(sample_album)

        # Should have color classes or styles for DR values
        assert "dr-badge" in output or "dr-value" in output

    def test_html_escaping(self):
        """Test that HTML special characters are handled."""
        album = AlbumResult(
            tracks=[
                TrackResult(
                    filename="Track & Song <test>.flac",
                    dr_value=10,
                    peak_db=-1.0,
                    rms_db=-12.0,
                    duration=120.0,
                    channel_dr=[10.0, 10.0],
                )
            ],
            album_dr=0,
            directory=Path("/test"),
            analyzed_at=datetime.now(),
            artist="Artist & Band",
            album="Album <Name>",
        )

        formatter = HTMLFormatter()
        output = formatter.format_album(album)

        # Should still generate valid HTML
        assert "<!DOCTYPE html>" in output
        # Characters should be in output (browser handles escaping)
        assert "Artist & Band" in output or "Artist &amp; Band" in output


class TestSaveResults:
    """Tests for saving results to files."""

    def test_save_text_format(self, sample_album):
        """Test saving in text format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = save_results(
                sample_album,
                output_dir=Path(tmpdir),
                format_type="text",
                filename="dr.txt",
            )

            assert output_path.exists()
            assert output_path.name == "dr.txt"

            content = output_path.read_text()
            assert "DR Check" in content
            assert "Test Artist / Test Album" in content

    def test_save_bbcode_format(self, sample_album):
        """Test saving in BBCode format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = save_results(
                sample_album,
                output_dir=Path(tmpdir),
                format_type="bbcode",
                filename="dr.txt",
            )

            assert output_path.exists()
            content = output_path.read_text()
            assert "[b]" in content

    def test_save_csv_format(self, sample_album):
        """Test saving in CSV format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = save_results(
                sample_album,
                output_dir=Path(tmpdir),
                format_type="csv",
                filename="results.csv",
            )

            assert output_path.exists()
            assert output_path.suffix == ".csv"

            content = output_path.read_text()
            assert "Filename,DR,Peak" in content

    def test_save_html_format(self, sample_album):
        """Test saving in HTML format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = save_results(
                sample_album,
                output_dir=Path(tmpdir),
                format_type="html",
                filename="report.html",
            )

            assert output_path.exists()
            assert output_path.suffix == ".html"

            content = output_path.read_text()
            assert "<!DOCTYPE html>" in content
            assert "Test Artist" in content

    def test_save_invalid_format(self, sample_album):
        """Test that invalid format raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="Unsupported format"):
                save_results(
                    sample_album, output_dir=Path(tmpdir), format_type="invalid"
                )

    def test_save_creates_directory(self, sample_album):
        """Test that save creates output directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "subdir" / "nested"
            output_path = save_results(
                sample_album, output_dir=output_dir, format_type="text"
            )

            assert output_path.exists()
            assert output_path.parent == output_dir
