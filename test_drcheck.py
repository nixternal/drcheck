"""
Basic tests for DR Check components.
Run with: python test_drcheck.py /path/to/audio/file.flac
"""

import logging
import sys
from pathlib import Path

# Configure logging to see debug output
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Import our modules (adjust import paths based on your project structure)
from drcheck.analysis import compute_dr14
from drcheck.audio import (
    get_supported_extensions,
    is_supported_file,
    read_audio_file,
)


def test_supported_formats():
    """Test: Check what formats are supported."""
    print("\n=== Supported Audio Formats ===")
    formats = get_supported_extensions()
    print(f"Supported extensions: {', '.join(sorted(formats))}")
    print(f"Total formats: {len(formats)}")


def test_audio_reading(filepath: Path):
    """Test: Read an audio file."""
    print(f"\n=== Testing Audio Reading ===")
    print(f"File: {filepath}")

    # Check if supported
    if not is_supported_file(filepath):
        print(f"❌ File extension not supported: {filepath.suffix}")
        return None

    # Try to read
    try:
        audio_data = read_audio_file(filepath)
        print(f"✅ Successfully read audio file")
        print(f"   {audio_data}")
        print(f"   Sample shape: {audio_data.samples.shape}")
        print(f"   Sample dtype: {audio_data.samples.dtype}")
        print(
            f"   Sample range: [{audio_data.samples.min():.6f}, {audio_data.samples.max():.6f}]"
        )
        return audio_data
    except Exception as e:
        print(f"❌ Failed to read: {e}")
        return None


def test_dr14_calculation(audio_data):
    """Test: Calculate DR14 value."""
    print(f"\n=== Testing DR14 Calculation ===")

    try:
        result = compute_dr14(audio_data.samples, audio_data.sample_rate)
        print(f"✅ Successfully calculated DR14")
        print(f"   {result}")
        print(f"   DR14 value: {result.dr14}")
        print(f"   Peak: {result.peak_db:.2f} dB")
        print(f"   RMS: {result.rms_db:.2f} dB")
        print(f"   Per-channel DR: {result.channel_dr}")
        return result
    except Exception as e:
        print(f"❌ Failed to calculate DR14: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_synthetic_audio():
    """Test: Create synthetic audio and verify DR calculation."""
    import numpy as np

    print(f"\n=== Testing with Synthetic Audio ===")

    # Create 10 seconds of stereo sine wave at 440Hz
    sample_rate = 44100
    duration = 10.0
    frequency = 440.0

    t = np.linspace(0, duration, int(sample_rate * duration))

    # Left channel: full amplitude
    left = np.sin(2 * np.pi * frequency * t) * 0.8

    # Right channel: half amplitude (should have higher DR)
    right = np.sin(2 * np.pi * frequency * t) * 0.4

    # Combine into stereo
    samples = np.column_stack([left, right])

    print(f"Generated {duration}s stereo sine wave at {frequency}Hz")
    print(f"Shape: {samples.shape}, dtype: {samples.dtype}")

    try:
        result = compute_dr14(samples, sample_rate)
        print(f"✅ DR14 calculation successful")
        print(f"   DR14: {result.dr14}")
        print(f"   Peak: {result.peak_db:.2f} dB")
        print(f"   RMS: {result.rms_db:.2f} dB")
        print(f"   Channel DR: {result.channel_dr}")

        # For a pure sine wave, DR should be very low (highly compressed)
        if result.dr14 < 5:
            print(f"   ✅ DR value makes sense for sine wave (low dynamic range)")
        else:
            print(f"   ⚠️  DR value seems high for a sine wave")

    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback

        traceback.print_exc()


def main():
    """Run all tests."""
    print("=" * 60)
    print("DR14 T.meter - Component Tests")
    print("=" * 60)

    # Test 1: Check supported formats
    test_supported_formats()

    # Test 2: Synthetic audio (always works)
    test_synthetic_audio()

    # Test 3: Real audio file (if provided)
    if len(sys.argv) > 1:
        filepath = Path(sys.argv[1])
        audio_data = test_audio_reading(filepath)

        if audio_data:
            test_dr14_calculation(audio_data)
    else:
        print("\n" + "=" * 60)
        print("To test with a real audio file, run:")
        print(f"  python {sys.argv[0]} /path/to/audio.flac")
        print("=" * 60)

    print("\n" + "=" * 60)
    print("Tests complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
