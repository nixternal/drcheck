"""
Tests for parallel processing module.
"""

import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from drcheck.parallel import (
    AnalysisResult,
    AnalysisTask,
    ParallelAnalyzer,
    _analyze_single_file,
    get_default_workers,
)


def create_test_wav(
    filepath: Path, duration: float = 10.0, sample_rate: int = 44100, channels: int = 2
):
    """Create a test WAV file for analysis."""
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
def temp_audio_dir():
    """Create a temporary directory with test audio files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_audio_files(temp_audio_dir):
    """Create multiple test audio files."""
    files = []
    for i in range(5):
        filepath = temp_audio_dir / f"track_{i:02d}.wav"
        create_test_wav(filepath, duration=10.0)
        files.append(filepath)
    return files


class TestAnalysisTask:
    """Tests for AnalysisTask dataclass."""

    def test_task_creation(self, temp_audio_dir):
        """Test creating an analysis task."""
        filepath = temp_audio_dir / "test.wav"
        task = AnalysisTask(filepath=filepath, index=0, total=5)

        assert task.filepath == filepath
        assert task.index == 0
        assert task.total == 5


class TestAnalysisResult:
    """Tests for AnalysisResult dataclass."""

    def test_success_property_true(self, sample_audio_files):
        """Test success property when analysis succeeded."""
        task = AnalysisTask(filepath=sample_audio_files[0], index=0, total=1)
        result = _analyze_single_file(task)

        assert result.success is True
        assert result.error is None
        assert result.dr_result is not None
        assert result.audio_data is not None
        assert result.audio_data.samples is None  # Verify samples are stripped

    def test_success_property_false(self, temp_audio_dir):
        """Test success property when analysis failed."""
        # Create a fake file that can't be read
        fake_file = temp_audio_dir / "fake.wav"
        fake_file.write_bytes(b"not a real audio file")

        task = AnalysisTask(filepath=fake_file, index=0, total=1)
        result = _analyze_single_file(task)

        assert result.success is False
        assert result.error is not None
        assert result.dr_result is None


class TestAnalyzeSingleFile:
    """Tests for the _analyze_single_file worker function."""

    def test_analyze_valid_file(self, sample_audio_files):
        """Test analyzing a valid audio file."""
        task = AnalysisTask(filepath=sample_audio_files[0], index=0, total=1)
        result = _analyze_single_file(task)

        assert result.success
        assert result.filepath == sample_audio_files[0]
        assert result.index == 0
        assert result.dr_result is not None
        assert result.dr_result.dr14 >= 0

    def test_analyze_nonexistent_file(self, temp_audio_dir):
        """Test analyzing a file that doesn't exist."""
        filepath = temp_audio_dir / "nonexistent.wav"
        task = AnalysisTask(filepath=filepath, index=0, total=1)
        result = _analyze_single_file(task)

        assert not result.success
        assert "not found" in result.error.lower() or "no such file" in result.error.lower()


class TestParallelAnalyzer:
    """Tests for ParallelAnalyzer class."""

    def test_default_workers(self):
        """Test default worker count."""
        analyzer = ParallelAnalyzer()
        assert analyzer.workers >= 1

    def test_custom_workers(self):
        """Test custom worker count."""
        analyzer = ParallelAnalyzer(workers=4)
        assert analyzer.workers == 4

    def test_single_worker_fallback(self):
        """Test that single worker uses sequential processing."""
        analyzer = ParallelAnalyzer(workers=1)
        assert analyzer.workers == 1

    def test_analyze_empty_list(self):
        """Test analyzing empty file list."""
        analyzer = ParallelAnalyzer(workers=2)
        results = analyzer.analyze_files([])
        assert results == []

    def test_analyze_single_file(self, sample_audio_files):
        """Test analyzing a single file (uses sequential path)."""
        analyzer = ParallelAnalyzer(workers=2)
        results = analyzer.analyze_files([sample_audio_files[0]])

        assert len(results) == 1
        assert results[0].success
        assert results[0].filepath == sample_audio_files[0]

    def test_analyze_multiple_files_sequential(self, sample_audio_files):
        """Test analyzing multiple files with single worker."""
        analyzer = ParallelAnalyzer(workers=1)
        results = analyzer.analyze_files(sample_audio_files)

        assert len(results) == len(sample_audio_files)
        assert all(r.success for r in results)

    def test_analyze_multiple_files_parallel(self, sample_audio_files):
        """Test analyzing multiple files in parallel."""
        analyzer = ParallelAnalyzer(workers=2)
        results = analyzer.analyze_files(sample_audio_files)

        assert len(results) == len(sample_audio_files)
        assert all(r.success for r in results)

    def test_results_maintain_order(self, sample_audio_files):
        """Test that results maintain original file order."""
        analyzer = ParallelAnalyzer(workers=2)
        results = analyzer.analyze_files(sample_audio_files)

        # Results should be in the same order as input files
        for i, (result, original_file) in enumerate(zip(results, sample_audio_files)):
            assert result.filepath == original_file
            assert result.index == i

    def test_progress_callback(self, sample_audio_files):
        """Test that progress callback is called correctly."""
        analyzer = ParallelAnalyzer(workers=1)  # Use sequential for predictable order
        callback_calls = []

        def callback(completed, total, filepath, success):
            callback_calls.append((completed, total, filepath, success))

        analyzer.analyze_files(sample_audio_files, progress_callback=callback)

        assert len(callback_calls) == len(sample_audio_files)
        # Check that completed count increases
        for i, (completed, total, filepath, success) in enumerate(callback_calls):
            assert completed == i + 1
            assert total == len(sample_audio_files)
            assert success is True


class TestGetDefaultWorkers:
    """Tests for get_default_workers function."""

    def test_returns_positive_int(self):
        """Test that default workers is a positive integer."""
        workers = get_default_workers()
        assert isinstance(workers, int)
        assert workers >= 1
