"""
DR Check - Dynamic Range Analysis
Core calculation module for DR14 measurements.
"""

import logging
from dataclasses import dataclass
from typing import Union

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


@dataclass
class DR14Result:
    """Results from DR14 analysis of an audio file."""

    dr14: int
    peak_db: float
    rms_db: float
    channel_dr: NDArray[np.float32]  # Per-channel DR values

    def __str__(self) -> str:
        return f"DR{self.dr14} (Peak: {self.peak_db:.2f} dB, RMS: {self.rms_db:.2f} dB)"


def compute_dr14(
    audio_data: NDArray[np.float32],
    sample_rate: int,
    block_duration: float = 3.0,
    percentile_cutoff: float = 0.2,
) -> DR14Result:
    """
    Calculate DR14 (Dynamic Range) value for audio data.

    The DR14 algorithm:
    1. Divides audio into fixed-duration blocks (default 3 seconds)
    2. Calculates RMS and peak for each block
    3. Uses top 20% of blocks (by RMS) for final calculation
    4. DR = -20 * log10(mean_rms_top20% / second_highest_peak)

    Args:
        audio_data: Audio samples as numpy array. Shape: (samples,) for mono,
                   (samples, channels) for multi-channel
        sample_rate: Sample rate in Hz
        block_duration: Duration of each analysis block in seconds
        percentile_cutoff: Fraction of loudest blocks to use (0.2 = top 20%)

    Returns:
        DR14Result containing the DR14 value and related measurements

    Raises:
        ValueError: If audio is too short for analysis
    """
    # Ensure audio_data is 2D (samples, channels)
    if audio_data.ndim == 1:
        audio_data = audio_data.reshape(-1, 1)

    num_samples, num_channels = audio_data.shape

    # Apply sample rate correction (legacy compatibility with original implementation)
    delta_samples = 60 if sample_rate == 44100 else 0
    block_samples = int(block_duration * (sample_rate + delta_samples))

    num_blocks = int(np.floor(num_samples / block_samples)) + 1

    if num_blocks < 2:
        raise ValueError(
            f"Audio too short for DR analysis: {num_samples} samples "
            f"at {sample_rate} Hz = {num_samples / sample_rate:.2f} seconds. "
            f"Need at least {block_samples * 2 / sample_rate:.1f} seconds for reliable analysis."
        )

    logger.debug(
        f"Computing DR14: {num_samples} samples, {sample_rate} Hz, "
        f"{num_channels} channels, {num_blocks} blocks"
    )

    # Allocate arrays for block statistics
    rms_blocks = np.zeros((num_blocks, num_channels))
    peak_blocks = np.zeros((num_blocks, num_channels))

    # Process complete blocks
    current_sample = 0
    for i in range(num_blocks - 1):
        block = audio_data[current_sample : current_sample + block_samples, :]
        rms_blocks[i, :] = _calculate_rms(block)
        peak_blocks[i, :] = np.max(np.abs(block), axis=0)
        current_sample += block_samples

    # Process final partial block if it exists
    if current_sample < num_samples:
        final_block = audio_data[current_sample:, :]
        rms_blocks[-1, :] = _calculate_rms(final_block)
        peak_blocks[-1, :] = np.max(np.abs(final_block), axis=0)

    # Calculate how many of the loudest blocks to use
    num_top_blocks = max(1, int(np.floor(num_blocks * percentile_cutoff)))

    # Use np.partition for O(n) instead of O(n log n) full sort
    # We only need the top percentile, not full sorted order
    partition_idx = num_blocks - num_top_blocks

    # Partition RMS blocks - values at partition_idx and above are the largest
    rms_partitioned = np.partition(rms_blocks, partition_idx, axis=0)
    top_rms_blocks = rms_partitioned[partition_idx:, :]

    # Calculate mean RMS of top blocks
    rms_squared_sum = np.sum(top_rms_blocks**2, axis=0)
    mean_rms_top = np.sqrt(rms_squared_sum / num_top_blocks)

    # Partition peak blocks to find second-highest (avoid outliers/clipping)
    # Partition at -2 position to get the second highest value
    peak_partitioned = np.partition(peak_blocks, -2, axis=0)
    second_highest_peak = peak_partitioned[-2, :]

    # Calculate DR per channel: -20 * log10(rms / peak)
    # Check for invalid values before calculation
    with np.errstate(divide="ignore", invalid="ignore"):
        channel_dr = -20.0 * np.log10(mean_rms_top / second_highest_peak)

    # Handle edge cases (silence, extremely low RMS, NaN, inf, negative values)
    MIN_AUDIO_LEVEL = 1e-10
    MAX_DR_VALUE = 200  # Sanity check for 24-bit audio
    MIN_DR_VALUE = 0.01  # Minimum meaningful DR value

    invalid_channels = np.logical_or.reduce(
        [
            rms_squared_sum < MIN_AUDIO_LEVEL,
            np.abs(channel_dr) > MAX_DR_VALUE,
            channel_dr < MIN_DR_VALUE,  # Catch near-zero and negative values
            np.isnan(channel_dr),
            np.isinf(channel_dr),
        ]
    )
    channel_dr[invalid_channels] = 0.0

    # Final DR14 is the rounded mean across all channels
    # Handle case where all channels are invalid
    valid_drs = channel_dr[~invalid_channels]
    if len(valid_drs) > 0:
        dr14_value = int(round(np.mean(valid_drs)))
    else:
        dr14_value = 0

    # Calculate overall peak and RMS in dB
    overall_peak = np.max(peak_blocks)
    peak_db = _to_decibels(overall_peak)

    overall_rms = _calculate_rms(audio_data)
    rms_db = _to_decibels(np.mean(overall_rms))

    logger.info(f"DR14 calculation complete: DR{dr14_value}")

    return DR14Result(
        dr14=dr14_value, peak_db=peak_db, rms_db=rms_db, channel_dr=channel_dr
    )


def _calculate_rms(audio_block: NDArray[np.float32]) -> NDArray[np.float32]:
    """
    Calculate RMS (Root Mean Square) for audio block.

    Args:
        audio_block: Audio samples, shape (samples, channels)

    Returns:
        RMS value per channel
    """
    num_samples = audio_block.shape[0]
    return np.sqrt(2.0 * np.sum(audio_block**2, axis=0) / num_samples)


def _to_decibels(value: Union[float, np.float32], reference: float = 1.0) -> float:
    """
    Convert linear amplitude to decibels.

    Args:
        value: Linear amplitude value
        reference: Reference level (default 1.0 for full scale)

    Returns:
        Value in decibels
    """
    if value <= 0:
        return float("-inf")
    return float(20.0 * np.log10(value / reference))
