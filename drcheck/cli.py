"""
DR Check - Command Line Interface
Main entry point for the DR14 meter application.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

import click
from drcheck.audio import (
    AudioData,
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
from drcheck.__version__ import __version__


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
                click.echo(f"Skipping unsupported file: {path}", err=True)
        elif path.is_dir():
            found_files = find_audio_files(path, recursive=recursive)
            if not found_files:
                click.echo(f"No audio files found in: {path}", err=True)
            files_to_process.extend(found_files)
            if base_directory is None:
                base_directory = path
        else:
            click.echo(f"Invalid path: {path}", err=True)

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

    # Progress callback for parallel processing
    def progress_callback(completed: int, total: int, filepath: Path, success: bool) -> None:
        status = "✓" if success else "✗"
        click.echo(f"[{completed}/{total}] {status} {filepath.name}")

    # Process files (parallel or sequential based on workers)
    results = analyzer.analyze_files(files_to_process, progress_callback)

    # Collect results
    track_results: list[TrackResult] = []
    failed: list[tuple[Path, str]] = []
    artist: str | None = None
    album_name: str | None = None

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
                f"  DR{dr_result.dr14:<2} | Peak: {dr_result.peak_db:>6.2f} dB | "
                f"RMS: {dr_result.rms_db:>6.2f} dB"
            )

            if show_channels and len(dr_result.channel_dr) > 1:
                channel_info = " | ".join(
                    f"Ch{i + 1}: DR{dr:.2f}"
                    for i, dr in enumerate(dr_result.channel_dr)
                )
                click.echo(f"       {channel_info}")
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
        if output_format != "html":
            print_results(
                album=album_result,
                format_type=output_format,
                show_channels=show_channels,
            )
        else:
            click.echo("HTML report generated (use --save to write to file)")

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
        click.echo(f"\n❌ Failed to process: {len(failed)} file(s)", err=True)
        for filepath, error in failed:
            click.echo(f"  {filepath.name}: {error}", err=True)
        sys.exit(1)

    click.echo()


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
