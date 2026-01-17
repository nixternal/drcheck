"""
DR Check - Command Line Interface
Main entry point for the DR14 meter application.
"""

import logging
import platform
import sys
from datetime import datetime
from pathlib import Path

import click

from drcheck.__version__ import __version__
from drcheck.audio import (
    AudioData,
    AudioReadError,
    UnsupportedFormatError,
    find_audio_files,
    is_supported_file,
)
from drcheck.formatters import (
    AlbumResult,
    TrackResult,
    print_results,
    save_results,
)
from drcheck.parallel import ParallelAnalyzer, get_default_workers


# Setup logging
def setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure logging based on verbosity flags."""
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def format_error_message(filepath: Path, error: str) -> tuple[str, str]:
    """
    Format error message with helpful suggestion based on error type.

    Args:
        filepath: Path that caused the error
        error: Error message string

    Returns:
        Tuple of (error_category, formatted_message)
    """
    error_lower = error.lower()
    filename = filepath.name
    ext = filepath.suffix.upper()

    # File not found errors
    if "not found" in error_lower or "no such file" in error_lower:
        return ("File Not Found", f"{filename}")

    # Permission/access errors
    if "permission" in error_lower or "access" in error_lower:
        return ("Permission Denied", f"{filename} (check file permissions)")

    # Format/codec errors
    if (
        "format" in error_lower
        or "codec" in error_lower
        or "unsupported" in error_lower
    ):
        if ext in {".MP3", ".M4A", ".AAC", ".WMA"}:
            return (
                "Missing Lossy Format Support",
                f"{filename}\n"
                f"     → Install: pip install drcheck[lossy]\n"
                f"     → Also ensure ffmpeg is installed on your system",
            )
        return (
            "Unsupported Format",
            f"{filename} ({ext} format not supported or file corrupted)",
        )

    # Corrupted file errors
    if (
        "corrupted" in error_lower
        or "invalid" in error_lower
        or "decode" in error_lower
    ):
        return ("Corrupted File", f"{filename} (file appears corrupted or invalid)")

    # Audio too short errors
    if "too short" in error_lower:
        return (
            "Audio Too Short",
            f"{filename} (need at least 6 seconds for DR analysis)",
        )

    # Memory errors
    if "memory" in error_lower:
        return ("Memory Error", f"{filename} (file too large or insufficient memory)")

    # Generic errors
    return ("Error", f"{filename}: {error}")


def show_processing_summary(total_files: int, successful: int, failed: int) -> None:
    """
    Display a summary of processing results.

    Args:
        total_files: Total number of files attempted
        successful: Number of successfully processed files
        failed: Number of failed files
    """
    click.echo(f"\n{'=' * 80}")
    click.echo(f"Processing Summary: {successful}/{total_files} files successful")
    click.echo(f"{'=' * 80}")

    if failed > 0:
        click.echo(f"❌ {failed} file(s) failed")
    if successful > 0:
        click.echo(f"✅ {successful} file(s) processed successfully")


@click.group(invoke_without_command=True)
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
@click.option("-q", "--quiet", is_flag=True, help="Only show errors")
@click.option("--version", is_flag=True, help="Show version and exit")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool, version: bool) -> None:
    """
    DR Check - Dynamic Range Analyzer

    Calculate DR14 values for audio files and albums.
    """
    setup_logging(verbose, quiet)

    if version:
        click.echo(f"DR Check v{__version__} - Dynamic Range Analyzer")
        ctx.exit(0)

    # If no subcommand provided, show help
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument(
    "paths", nargs=-1, type=click.Path(exists=True, path_type=Path), required=True
)
@click.option("-r", "--recursive", is_flag=True, help="Recursively scan directories")
@click.option("--show-channels", is_flag=True, help="Show per-channel DR values")
@click.option("--save", is_flag=True, help="Save results to file")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output directory (default: source directory)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "bbcode", "csv", "html"], case_sensitive=False),
    default="text",
    help="Output format",
)
@click.option(
    "--filename",
    default="dr.txt",
    help="Output filename (default: dr.txt, auto-adjusts extension)",
)
@click.option(
    "-j",
    "--workers",
    type=int,
    default=None,
    help="Parallel workers (auto: sequential for <20 files, parallel for larger jobs)",
)
def analyze(
    paths: tuple[Path, ...],
    recursive: bool,
    show_channels: bool,
    save: bool,
    output: Path | None,
    output_format: str,
    filename: str,
    workers: int | None,
) -> None:
    """
    Analyze audio files and calculate DR14 values.

    PATHS can be individual files or directories. Directories will be
    scanned for supported audio files.

    Examples:

      drcheck analyze song.flac

      drcheck analyze album_folder/

      drcheck analyze -r music_library/

      drcheck analyze album/ --save

      drcheck analyze album/ --save --format bbcode

      drcheck analyze album/ --format csv > results.csv

      drcheck analyze album/ -j 4  # Use 4 parallel workers

    \b
    Notes:
      * for MP3/M4A support: pip install drcheck[lossy]
      * for optimized HTML reports: pip install drcheck[html]
      * Files are processed in parallel for large jobs (20+ files)
      * Use -j 1 to force sequential processing
    """
    # Collect all audio files to process
    files_to_process: list[Path] = []
    base_directory: Path | None = None

    for path in paths:
        if path.is_file():
            if is_supported_file(path):
                files_to_process.append(path)
                if base_directory is None:
                    base_directory = path.parent
            else:
                ext = path.suffix.upper()
                if ext in {".MP3", ".M4A", ".AAC", ".WMA"}:
                    click.echo(
                        f"⚠️  Skipping {ext}: {path.name}\n"
                        f"    Install lossy format support: pip install drcheck[lossy]",
                        err=True,
                    )
                else:
                    click.echo(
                        f"⚠️  Skipping unsupported format: {path.name} ({ext})", err=True
                    )
        elif path.is_dir():
            found_files = find_audio_files(path, recursive=recursive)
            if not found_files:
                click.echo(f"No audio files found in: {path}", err=True)
            files_to_process.extend(found_files)
            if base_directory is None:
                base_directory = path
        else:
            click.echo(
                f"❌ Invalid path: {path}\n"
                f"    Path must be an existing file or directory",
                err=True,
            )

    if not files_to_process:
        click.echo("No audio files to process", err=True)
        sys.exit(1)

    if base_directory is None:
        base_directory = Path.cwd()

    click.echo(f"Found {len(files_to_process)} file(s) to analyze\n")

    # Smart worker selection: avoid multiprocessing overhead for small jobs
    # Threshold of 20 files balances overhead vs parallelization benefit
    PARALLEL_THRESHOLD = 20

    if workers is not None:
        # User explicitly set workers - respect their choice
        effective_workers = workers
    elif len(files_to_process) < PARALLEL_THRESHOLD:
        # Small job - sequential is more efficient (avoids IPC overhead)
        effective_workers = 1
    else:
        # Large job - use parallel processing
        effective_workers = get_default_workers()

    if effective_workers > 1:
        click.echo(f"Using {effective_workers} parallel workers\n")

    analyzer = ParallelAnalyzer(workers=effective_workers)

    # Track processing statistics
    processing_stats = {"successful": 0, "failed": 0}

    def progress_callback(
        completed: int, total: int, filepath: Path, success: bool
    ) -> None:
        """Updated progress display"""
        status = "✅" if success else "❌"
        percentage = (completed / total) * 100
        click.echo(
            f"[{completed}/{total} - {percentage:5.1f}%] {status} {filepath.name}"
        )
        if success:
            processing_stats["successful"] += 1
        else:
            processing_stats["failed"] += 1

    # Process files (parallel or sequential based on workers)
    results = analyzer.analyze_files(files_to_process, progress_callback)

    # Collect results
    track_results: list[TrackResult] = []
    failed: list[tuple[Path, str]] = []
    artist: str | None = None
    album_name: str | None = None
    total_processed = 0

    for result in results:
        if result.success and result.audio_data and result.dr_result:
            audio_data = result.audio_data
            dr_result = result.dr_result

            # Capture artist/album from first track that has them
            if artist is None and audio_data.artist:
                artist = audio_data.artist
            if album_name is None and audio_data.album:
                album_name = audio_data.album

            # Create track result
            track_result = TrackResult.from_dr14_result(
                filepath=result.filepath,
                result=dr_result,
                duration=audio_data.duration_seconds,
                sample_rate=audio_data.sample_rate,
                channels=audio_data.channels,
                bit_depth=audio_data.bit_depth,
                format_name=audio_data.format_name,
            )
            track_results.append(track_result)

            # Display results for this track
            click.echo(
                f"    DR{dr_result.dr14:<2} | Peak: {dr_result.peak_db:>6.2f} dB | "
                f"RMS: {dr_result.rms_db:>6.2f} dB"
            )

            if show_channels and len(dr_result.channel_dr) > 1:
                channel_info = " | ".join(
                    f"Ch{i + 1}: DR{dr:.2f}"
                    for i, dr in enumerate(dr_result.channel_dr)
                )
                click.echo(f"         {channel_info}")

            total_processed += 1
        else:
            failed.append((result.filepath, result.error or "Unknown error"))

    # Create album result
    if track_results:
        album_result = AlbumResult(
            tracks=track_results,
            album_dr=0,  # Will be calculated in __post_init__
            directory=base_directory,
            analyzed_at=datetime.now(),
            artist=artist,
            album=album_name,
        )

        # Display formatted output (skip for HTML as it's too verbose)
        click.echo("\n")
        if output_format == "html":
            click.echo("HTML report generated (use --save to write to file)")
        else:
            print_results(
                album=album_result,
                format_type=output_format,
                show_channels=show_channels,
            )

        # Save to file if requested
        if save:
            output_dir = output if output else base_directory
            saved_path = save_results(
                album=album_result,
                output_dir=output_dir,
                format_type=output_format,
                filename=filename,
                show_channels=show_channels,
                audio_files=files_to_process,
            )
            click.echo(f"\n✅ Results saved to: {saved_path}")

    # Show failures if any
    if failed:
        click.echo(f"\n{'=' * 80}", err=True)
        click.echo(
            f"⚠️  Failed to process {len(failed)} of {len(files_to_process)} file(s)",
            err=True,
        )
        click.echo(f"{'=' * 80}\n", err=True)

        # Group errors by category for better presentation
        error_groups: dict[str, list[tuple[Path, str]]] = {}
        for filepath, error in failed:
            category, formatted_msg = format_error_message(filepath, error)

            if category not in error_groups:
                error_groups[category] = []
            error_groups[category].append((filepath, formatted_msg))

        # Display grouped errors with helpful context
        for category, file_errors in sorted(error_groups.items()):
            click.echo(f"📋 {category} ({len(file_errors)} file(s)):", err=True)
            for filepath, formatted_msg in file_errors:
                # Indent multi-line messages properly
                lines = formatted_msg.split("\n")
                click.echo(f"   • {lines[0]}", err=True)
                for line in lines[1:]:
                    click.echo(f"     {line}", err=True)
            click.echo("", err=True)  # Blank line between categories

        click.echo(f"{'=' * 80}", err=True)

        # Provide helpful suggestions based on error types
        has_lossy_errors = "Missing Lossy Format Support" in error_groups
        has_corrupted = "Corrupted File" in error_groups
        has_short_audio = "Audio Too Short" in error_groups

        # Show actionable tips
        if has_lossy_errors or has_corrupted or has_short_audio:
            click.echo("\n💡 Tips:", err=True)

            if has_lossy_errors:
                click.echo(
                    "   • For MP3/M4A support, install:\n"
                    "     pip install drcheck[lossy]\n"
                    "     Also ensure ffmpeg is installed on your system",
                    err=True,
                )

            if has_corrupted:
                click.echo(
                    "   • Corrupted files may need to be:\n"
                    "     - Re-downloaded from original source\n"
                    "     - Re-ripped from CD\n"
                    "     - Converted to a different format",
                    err=True,
                )

            if has_short_audio:
                click.echo(
                    "   • DR analysis requires at least 6 seconds of audio\n"
                    "     (two 3-second blocks for measurement)",
                    err=True,
                )

        # Summary statistics
        click.echo(f"\n{'=' * 80}", err=True)
        if total_processed > 0:
            success_rate = (total_processed / len(files_to_process)) * 100
            click.echo(
                f"✅ Successfully processed: {total_processed}/{len(files_to_process)} "
                f"({success_rate:.1f}%)",
                err=True,
            )
        else:
            click.echo("❌ No files were successfully processed", err=True)

        click.echo(f"{'=' * 80}", err=True)

        # Show help hint
        click.echo("\n💬 Need help? Run: drcheck --help", err=True)
        click.echo(
            "🐛 Found a bug? Report at: https://github.com/nixternal/drcheck/issues\n",
            err=True,
        )

        # Exit with error code only if ALL files failed
        if total_processed == 0:
            sys.exit(1)
        else:
            # Partial success - show warning but don't exit with error
            click.echo(f"⚠️  Completed with {len(failed)} error(s)\n", err=True)
    else:
        # All files successful
        if total_processed > 0:
            click.echo(f"\n✅ Successfully analyzed all {total_processed} file(s)")

    click.echo()  # Final blank line


@cli.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("-r", "--recursive", is_flag=True, help="Recursively scan directories")
def scan(path: Path, recursive: bool) -> None:
    """
    Scan a directory and show all supported audio files.

    This is useful to preview what files will be analyzed without
    actually processing them.
    """
    if not path.is_dir():
        click.echo(f"Error: {path} is not a directory", err=True)
        sys.exit(1)

    files = find_audio_files(path, recursive=recursive)

    if not files:
        click.echo(f"No supported audio files found in: {path}")
        sys.exit(0)

    click.echo(f"Found {len(files)} audio file(s) in {path}:")
    click.echo()

    # Group by extension
    by_ext: dict[str, list[Path]] = {}
    for f in files:
        ext = f.suffix.lower()
        by_ext.setdefault(ext, []).append(f)

    for ext in sorted(by_ext.keys()):
        click.echo(f"{ext.upper()} files: {len(by_ext[ext])}")
        for f in sorted(by_ext[ext]):
            # Show relative path if in subdirectory
            try:
                rel_path = f.relative_to(path)
            except ValueError:
                rel_path = f
            click.echo(f"  {rel_path}")
        click.echo()


@cli.command()
def formats() -> None:
    """Show supported audio formats."""
    from drcheck.audio import get_supported_extensions

    extensions = get_supported_extensions()

    click.echo("Supported audio formats:")
    click.echo()

    # Categorize
    lossless = {".flac", ".wav", ".aiff", ".aif", ".aifc"}
    lossy = {".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".opus"}

    supported_lossless = sorted(extensions & lossless)
    supported_lossy = sorted(extensions & lossy)

    if supported_lossless:
        click.echo("Lossless:")
        for ext in supported_lossless:
            click.echo(f"  {ext}")
        click.echo()

    if supported_lossy:
        click.echo("Lossy:")
        for ext in supported_lossy:
            click.echo(f"  {ext}")
        click.echo()

    click.echo(f"Total: {len(extensions)} format(s)")


@cli.command()
def version() -> None:
    """Show version information and system details"""
    from drcheck.audio import get_supported_extensions

    click.echo(f"DR Check v{__version__}")
    click.echo("Dynamic Range Analyzer")
    click.echo()

    # Show Python version
    click.echo(f"Python: {platform.python_version()}")
    click.echo(f"Platform: {platform.system()} {platform.machine()}")
    click.echo()

    # Show supported formats
    extensions = get_supported_extensions()

    # Categorize formats
    lossless = {".flac", ".wav", ".aiff", ".aif", ".aifc"}
    lossy = {".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".opus"}

    supported_lossless = sorted(extensions & lossless)
    supported_lossy = sorted(extensions & lossy)

    click.echo("Supported formats:")
    if supported_lossless:
        click.echo(f"  Lossless: {', '.join(supported_lossless)}")
    if supported_lossy:
        click.echo(f"  Lossy: {', '.join(supported_lossy)}")

    click.echo()
    click.echo("https://github.com/nixternal/drcheck")


def main() -> None:
    """Main entry point."""
    try:
        cli(obj={})
    except KeyboardInterrupt:
        click.echo("\nInterrupted by user", err=True)
        sys.exit(130)
    except Exception as e:
        click.echo(f"Fatal error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
