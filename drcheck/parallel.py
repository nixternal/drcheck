"""
DR Check - Parallel Processing
Handles parallel analysis of multiple audio files.
"""

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from drcheck import audio
from drcheck.analysis import DR14Result, compute_dr14
from drcheck.audio import AudioData, read_audio_file

logger = logging.getLogger(__name__)


@dataclass
class AnalysisTask:
    """Represents a single file analysis task."""

    filepath: Path
    index: int
    total: int


@dataclass
class AnalysisResult:
    """Result of a parallel analysis task."""

    filepath: Path
    audio_data: AudioData | None
    dr_result: DR14Result | None
    error: str | None
    index: int

    @property
    def success(self) -> bool:
        """Check if analysis was successful."""
        return self.error is None and self.dr_result is not None


def _analyze_single_file(task: AnalysisTask) -> AnalysisResult:
    """
    Analyze a single audio file (worker function).

    This function is designed to be called in a separate process.

    Args:
        task: AnalysisTask containing file path and metadata

    Returns:
        AnalysisResult with DR14 results or error
    """
    try:
        # Read audio file
        audio_data = read_audio_file(task.filepath)

        # Compute DR14
        dr_result = compute_dr14(audio_data.samples, audio_data.sample_rate)

        # Create lightweight metadata-only AudioData (no samples) instead of
        # just setting audio_data.samples = None - Memory Leak Fix
        metadata_only = AudioData(
            samples=None,  # Don't include samples
            sample_rate=audio_data.sample_rate,
            channels=audio_data.channels,
            duration_seconds=audio_data.duration_seconds,
            filepath=audio_data.filepath,
            bit_depth=audio_data.bit_depth,
            format_name=audio_data.format_name,
            artist=audio_data.artist,
            album=audio_data.album,
        )

        return AnalysisResult(
            filepath=task.filepath,
            audio_data=metadata_only,
            dr_result=dr_result,
            error=None,
            index=task.index,
        )

    except Exception as e:
        logger.debug(f"Failed to analyze {task.filepath}: {e}")
        return AnalysisResult(
            filepath=task.filepath,
            audio_data=None,
            dr_result=None,
            error=str(e),
            index=task.index,
        )


ProgressCallback = Callable[[int, int, Path, bool], None]


class ParallelAnalyzer:
    """
    Parallel audio file analyzer using process pools.

    Usage:
        analyzer = ParallelAnalyzer(workers=4)
        results = analyzer.analyze_files(file_list, progress_callback)
    """

    def __init__(self, workers: int | None = None):
        """
        Initialize parallel analyzer.

        Args:
            workers: Number of worker processes. Defaults to half of CPU count.
        """
        if workers is None:
            workers = max(1, (os.cpu_count() or 2) // 2)
        self.workers = workers
        logger.debug(f"ParallelAnalyzer initialized with {workers} workers")

    def analyze_files(
        self,
        files: list[Path],
        progress_callback: ProgressCallback | None = None,
    ) -> list[AnalysisResult]:
        """
        Analyze multiple audio files in parallel.

        Args:
            files: List of audio file paths to analyze
            progress_callback: Optional callback(index, total, filepath, success)
                Called after each file is processed.

        Returns:
            List of AnalysisResult objects in original file order
        """
        if not files:
            return []

        # Use sequential processing for single files or single worker
        if len(files) == 1 or self.workers == 1:
            return self._analyze_sequential(files, progress_callback)

        return self._analyze_parallel(files, progress_callback)

    def _analyze_sequential(
        self,
        files: list[Path],
        progress_callback: ProgressCallback | None = None,
    ) -> list[AnalysisResult]:
        """Analyze files sequentially (fallback for single file or worker=1)."""
        results = []
        total = len(files)

        for i, filepath in enumerate(files):
            task = AnalysisTask(filepath=filepath, index=i, total=total)
            result = _analyze_single_file(task)
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total, filepath, result.success)

        return results

    def _analyze_parallel(
        self,
        files: list[Path],
        progress_callback: ProgressCallback | None = None,
    ) -> list[AnalysisResult]:
        """Analyze files in parallel using ProcessPoolExecutor."""
        total = len(files)
        tasks = [
            AnalysisTask(filepath=f, index=i, total=total) for i, f in enumerate(files)
        ]

        # Pre-allocate results list to maintain order
        results: list[AnalysisResult | None] = [None] * total
        completed_count = 0

        with ProcessPoolExecutor(max_workers=self.workers) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(_analyze_single_file, task): task for task in tasks
            }

            # Process results as they complete
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                except Exception as e:
                    # Handle executor-level errors
                    result = AnalysisResult(
                        filepath=task.filepath,
                        audio_data=None,
                        dr_result=None,
                        error=f"Executor error: {e}",
                        index=task.index,
                    )

                # Store result in correct position
                results[result.index] = result
                completed_count += 1

                if progress_callback:
                    progress_callback(
                        completed_count, total, result.filepath, result.success
                    )

        # Type narrow: all positions should be filled
        return [r for r in results if r is not None]


def get_default_workers() -> int:
    """Get the default number of worker processes."""
    return max(1, (os.cpu_count() or 2) // 2)
