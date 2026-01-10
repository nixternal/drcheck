"""
Tests for DR14 calculation algorithm.
"""

import numpy as np
import pytest

from drcheck.analysis import DR14Result, compute_dr14


class TestDR14Calculation:
    """Tests for the core DR14 calculation."""

    def test_sine_wave_low_dynamic_range(self):
        """Test that a pure sine wave has low DR (highly compressed)."""
        # Generate 10 seconds of mono sine wave at 440Hz
        sample_rate = 44100
        duration = 10.0
        frequency = 440.0
        amplitude = 0.8

        t = np.linspace(0, duration, int(sample_rate * duration))
        samples = amplitude * np.sin(2 * np.pi * frequency * t)
        samples = samples.reshape(-1, 1)  # Make it 2D (mono)

        result = compute_dr14(samples, sample_rate)

        # Pure sine wave should have very low DR (typically DR1-DR5)
        assert isinstance(result, DR14Result)
        assert 0 <= result.dr14 <= 6, f"Sine wave DR should be low, got DR{result.dr14}"
        assert result.peak_db < 0  # Peak should be below 0 dBFS
        assert result.rms_db < result.peak_db  # RMS should be below peak

    def test_stereo_channels(self):
        """Test stereo audio processing."""
        sample_rate = 44100
        duration = 10.0

        t = np.linspace(0, duration, int(sample_rate * duration))

        # Left channel: sine wave
        left = 0.8 * np.sin(2 * np.pi * 440 * t)
        # Right channel: sine wave
        right = 0.4 * np.sin(2 * np.pi * 880 * t)

        samples = np.column_stack([left, right])

        result = compute_dr14(samples, sample_rate)

        # Main test: should process stereo correctly
        assert len(result.channel_dr) == 2
        # Pure sine waves have essentially zero dynamic range
        # The algorithm should detect this and return DR=0
        assert all(dr >= 0 for dr in result.channel_dr)
        assert result.dr14 >= 0
        assert isinstance(result.dr14, int)

    def test_silent_audio_handling(self):
        """Test that silent audio is handled gracefully."""
        sample_rate = 44100
        duration = 5.0

        # All zeros
        samples = np.zeros((int(sample_rate * duration), 2))

        result = compute_dr14(samples, sample_rate)

        # Silent audio should have DR of 0 (edge case handling)
        assert result.dr14 == 0
        assert result.peak_db == float("-inf") or result.peak_db < -100

    def test_mono_audio(self):
        """Test mono audio file."""
        sample_rate = 44100
        duration = 10.0

        t = np.linspace(0, duration, int(sample_rate * duration))
        samples = 0.5 * np.sin(2 * np.pi * 440 * t)
        samples = samples.reshape(-1, 1)

        result = compute_dr14(samples, sample_rate)

        assert len(result.channel_dr) == 1
        assert isinstance(result.dr14, int)

    def test_very_short_audio(self):
        """Test that very short audio raises an error."""
        sample_rate = 44100
        # Only 1 second (needs at least 6 seconds for two 3-second blocks)
        samples = np.random.randn(sample_rate, 2) * 0.1

        with pytest.raises(ValueError, match="Audio too short"):
            compute_dr14(samples, sample_rate)

    def test_dynamic_audio_higher_dr(self):
        """Test that audio with dynamics has higher DR than compressed audio."""
        sample_rate = 44100
        duration = 10.0
        num_samples = int(sample_rate * duration)

        # Create audio with varying amplitude (simulating dynamics)
        t = np.linspace(0, duration, num_samples)

        # Sine wave with amplitude modulation (creates dynamics)
        carrier = np.sin(2 * np.pi * 440 * t)
        modulator = 0.3 + 0.7 * np.sin(2 * np.pi * 0.5 * t)  # Slow amplitude variation
        dynamic_samples = (carrier * modulator * 0.8).reshape(-1, 1)

        # Pure sine wave (no dynamics)
        static_samples = (0.8 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1)

        dynamic_result = compute_dr14(dynamic_samples, sample_rate)
        static_result = compute_dr14(static_samples, sample_rate)

        # Dynamic audio should have higher DR
        assert dynamic_result.dr14 > static_result.dr14

    def test_clipped_audio(self):
        """Test audio that clips at maximum amplitude."""
        sample_rate = 44100
        duration = 10.0

        t = np.linspace(0, duration, int(sample_rate * duration))
        # Create sine wave that clips
        samples = np.sin(2 * np.pi * 440 * t)
        samples = np.clip(samples, -0.99, 0.99)  # Clip to prevent going to 1.0
        samples = samples.reshape(-1, 1)

        result = compute_dr14(samples, sample_rate)

        # Should still calculate DR without crashing
        assert isinstance(result.dr14, int)
        assert result.dr14 >= 0
        # Peak should be very close to 0 dBFS
        assert result.peak_db > -1.0

    def test_different_sample_rates(self):
        """Test that different sample rates work correctly."""
        duration = 10.0

        for sample_rate in [44100, 48000, 96000, 192000]:
            t = np.linspace(0, duration, int(sample_rate * duration))
            samples = (0.5 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1)

            result = compute_dr14(samples, sample_rate)

            # Should get similar DR regardless of sample rate
            assert 0 <= result.dr14 <= 6
            assert isinstance(result.dr14, int)

    def test_result_dataclass_fields(self):
        """Test that DR14Result has all expected fields."""
        sample_rate = 44100
        duration = 10.0

        t = np.linspace(0, duration, int(sample_rate * duration))
        samples = (0.5 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1)

        result = compute_dr14(samples, sample_rate)

        # Check all fields exist and have correct types
        assert isinstance(result.dr14, int)
        assert isinstance(result.peak_db, float)
        assert isinstance(result.rms_db, float)
        assert isinstance(result.channel_dr, np.ndarray)
        assert len(result.channel_dr) > 0

    def test_custom_block_duration(self):
        """Test using custom block duration parameter."""
        sample_rate = 44100
        duration = 10.0

        t = np.linspace(0, duration, int(sample_rate * duration))
        samples = (0.5 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1)

        # Use 2-second blocks instead of default 3-second
        result = compute_dr14(samples, sample_rate, block_duration=2.0)

        assert isinstance(result.dr14, int)
        assert result.dr14 >= 0

    def test_custom_percentile_cutoff(self):
        """Test using custom percentile cutoff parameter."""
        sample_rate = 44100
        duration = 10.0

        t = np.linspace(0, duration, int(sample_rate * duration))
        samples = (0.5 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1)

        # Use top 30% instead of default 20%
        result = compute_dr14(samples, sample_rate, percentile_cutoff=0.3)

        assert isinstance(result.dr14, int)
        assert result.dr14 >= 0


class TestDR14EdgeCases:
    """Test edge cases and error handling."""

    def test_single_sample(self):
        """Test that single sample raises error."""
        samples = np.array([[0.5]])

        with pytest.raises(ValueError):
            compute_dr14(samples, 44100)

    def test_nan_values(self):
        """Test handling of NaN values in audio."""
        sample_rate = 44100
        duration = 10.0  # Long enough for analysis

        samples = np.random.randn(int(sample_rate * duration), 2) * 0.5
        samples[100:200] = np.nan  # Insert some NaN values

        # Should handle gracefully, resulting in DR=0 due to invalid data
        result = compute_dr14(samples, sample_rate)
        assert result.dr14 == 0  # Invalid result due to NaN

    def test_inf_values(self):
        """Test handling of infinite values in audio."""
        sample_rate = 44100
        duration = 10.0  # Long enough for analysis

        samples = np.random.randn(int(sample_rate * duration), 2) * 0.5
        samples[100] = np.inf

        result = compute_dr14(samples, sample_rate)
        # Should handle without crashing, but result may be invalid (DR=0)
        assert isinstance(result.dr14, int)
        assert result.dr14 >= 0
