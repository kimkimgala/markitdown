# SPDX-FileCopyrightText: 2024-present Adam Fourney <adamfo@microsoft.com>
#
# SPDX-License-Identifier: MIT
import argparse
import os
import sys
import codecs
import io
import tempfile
import uuid
from typing import Any, Dict, List, Tuple
from textwrap import dedent
from importlib.metadata import entry_points
from .__about__ import __version__
from ._markitdown import MarkItDown, StreamInfo, DocumentConverterResult


def main():
    parser = argparse.ArgumentParser(
        description="Convert various file formats to markdown.",
        prog="markitdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        usage=dedent(
            """
            SYNTAX:

                markitdown <OPTIONAL: FILENAME>
                If FILENAME is empty, markitdown reads from stdin.
                If FILENAME is a directory, every file in it is converted to markdown.

            EXAMPLE:

                markitdown example.pdf

                OR

                cat example.pdf | markitdown

                OR

                markitdown < example.pdf

                OR to save to a file use

                markitdown example.pdf -o example.md

                OR

                markitdown example.pdf > example.md

                OR to convert every file in a folder use

                markitdown path-to-folder -o path-to-output-folder

                OR, to also recurse into subfolders

                markitdown path-to-folder -o path-to-output-folder -r

                OR, to overwrite existing output files when batch-converting

                markitdown path-to-folder -o path-to-output-folder --overwrite
            """
        ).strip(),
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="show the version number and exit",
    )

    parser.add_argument(
        "-o",
        "--output",
        help=(
            "Output file name. If not provided, output is written to stdout. "
            "If FILENAME is a directory, this is instead treated as the output "
            "directory (defaults to FILENAME itself, converting files in place)."
        ),
    )

    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="When FILENAME is a directory, also convert files in its subdirectories.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "When FILENAME is a directory, overwrite output .md files that "
            "already exist. By default, existing output files are skipped."
        ),
    )

    parser.add_argument(
        "-x",
        "--extension",
        help="Provide a hint about the file extension (e.g., when reading from stdin).",
    )

    parser.add_argument(
        "-m",
        "--mime-type",
        help="Provide a hint about the file's MIME type.",
    )

    parser.add_argument(
        "-c",
        "--charset",
        help="Provide a hint about the file's charset (e.g., UTF-8).",
    )

    cloud_group = parser.add_mutually_exclusive_group()
    cloud_group.add_argument(
        "-d",
        "--use-docintel",
        action="store_true",
        help="Use Document Intelligence to extract text instead of offline conversion. Requires a valid Document Intelligence Endpoint.",
    )

    cloud_group.add_argument(
        "--use-cu",
        "--use-content-understanding",
        action="store_true",
        dest="use_cu",
        help="Use Azure Content Understanding to extract text. Requires --cu-endpoint.",
    )

    parser.add_argument(
        "-e",
        "--endpoint",
        type=str,
        default=os.environ.get("MARKITDOWN_DOCINTEL_ENDPOINT") or None,
        help="Document Intelligence Endpoint. Required if using Document Intelligence. Defaults to the MARKITDOWN_DOCINTEL_ENDPOINT environment variable.",
    )

    parser.add_argument(
        "--cu-endpoint",
        type=str,
        default=os.environ.get("MARKITDOWN_CU_ENDPOINT") or None,
        help="Content Understanding Endpoint. Required if using --use-cu. Defaults to the MARKITDOWN_CU_ENDPOINT environment variable.",
    )

    parser.add_argument(
        "--cu-analyzer",
        type=str,
        help="Content Understanding analyzer ID. If not specified, auto-selects by file type.",
    )

    parser.add_argument(
        "--cu-file-types",
        type=str,
        help="Comma-separated list of file types to route to Content Understanding (e.g., pdf,jpeg,mp4). If omitted, all supported types are routed.",
    )

    parser.add_argument(
        "-p",
        "--use-plugins",
        action="store_true",
        help="Use 3rd-party plugins to convert files. Use --list-plugins to see installed plugins.",
    )

    parser.add_argument(
        "--list-plugins",
        action="store_true",
        help="List installed 3rd-party plugins. Plugins are loaded when using the -p or --use-plugin option.",
    )

    parser.add_argument(
        "--keep-data-uris",
        action="store_true",
        help="Keep data URIs (like base64-encoded images) in the output. By default, data URIs are truncated.",
    )

    parser.add_argument("filename", nargs="?")
    args = parser.parse_args()

    # Parse the extension hint
    extension_hint = args.extension
    if extension_hint is not None:
        extension_hint = extension_hint.strip().lower()
        if len(extension_hint) > 0:
            if not extension_hint.startswith("."):
                extension_hint = "." + extension_hint
        else:
            extension_hint = None

    # Parse the mime type
    mime_type_hint = args.mime_type
    if mime_type_hint is not None:
        mime_type_hint = mime_type_hint.strip()
        if len(mime_type_hint) > 0:
            if mime_type_hint.count("/") != 1:
                _exit_with_error(f"Invalid MIME type: {mime_type_hint}")
        else:
            mime_type_hint = None

    # Parse the charset
    charset_hint = args.charset
    if charset_hint is not None:
        charset_hint = charset_hint.strip()
        if len(charset_hint) > 0:
            try:
                charset_hint = codecs.lookup(charset_hint).name
            except LookupError:
                _exit_with_error(f"Invalid charset: {charset_hint}")
        else:
            charset_hint = None

    stream_info = None
    if (
        extension_hint is not None
        or mime_type_hint is not None
        or charset_hint is not None
    ):
        stream_info = StreamInfo(
            extension=extension_hint, mimetype=mime_type_hint, charset=charset_hint
        )

    if args.list_plugins:
        # List installed plugins, then exit
        print("Installed MarkItDown 3rd-party Plugins:\n")
        plugin_entry_points = list(entry_points(group="markitdown.plugin"))
        if len(plugin_entry_points) == 0:
            print("  * No 3rd-party plugins installed.")
            print(
                "\nFind plugins by searching for the hashtag #markitdown-plugin on GitHub.\n"
            )
        else:
            for entry_point in plugin_entry_points:
                print(f"  * {entry_point.name:<16}\t(package: {entry_point.value})")
            print(
                "\nUse the -p (or --use-plugins) option to enable 3rd-party plugins.\n"
            )
        sys.exit(0)

    if args.use_docintel:
        if args.endpoint is None:
            _exit_with_error(
                "Document Intelligence Endpoint is required when using Document Intelligence. "
                "Pass -e/--endpoint or set MARKITDOWN_DOCINTEL_ENDPOINT."
            )
        elif args.filename is None:
            _exit_with_error("Filename is required when using Document Intelligence.")

        markitdown = MarkItDown(
            enable_plugins=args.use_plugins, docintel_endpoint=args.endpoint
        )
    elif args.use_cu:
        if args.cu_endpoint is None:
            _exit_with_error(
                "Content Understanding Endpoint (--cu-endpoint) is required when using --use-cu. "
                "Pass --cu-endpoint or set MARKITDOWN_CU_ENDPOINT."
            )

        cu_kwargs: Dict[str, Any] = {
            "cu_endpoint": args.cu_endpoint,
        }
        if args.cu_analyzer is not None:
            cu_kwargs["cu_analyzer_id"] = args.cu_analyzer
        if args.cu_file_types is not None:
            # Parse comma-separated file types into ContentUnderstandingFileType list
            from .converters import ContentUnderstandingFileType

            type_names = [
                t.strip().lower() for t in args.cu_file_types.split(",") if t.strip()
            ]
            cu_types = []
            for name in type_names:
                # Try matching by value (e.g., "pdf", "jpeg", "mp4")
                try:
                    cu_types.append(ContentUnderstandingFileType(name))
                except ValueError:
                    _exit_with_error(f"Unknown file type: {name}")
            cu_kwargs["cu_file_types"] = cu_types

        markitdown = MarkItDown(enable_plugins=args.use_plugins, **cu_kwargs)
    else:
        markitdown = MarkItDown(enable_plugins=args.use_plugins)

    if args.filename is not None and os.path.isdir(args.filename):
        if stream_info is not None:
            _exit_with_error(
                "The -x/--extension, -m/--mime-type, and -c/--charset hints "
                "cannot be used when FILENAME is a directory."
            )
        _convert_directory(markitdown, args)
        return

    if args.filename is None:
        # Windows pipe-backed stdin can report seekable() even though it cannot rewind.
        result = markitdown.convert_stream(
            io.BytesIO(sys.stdin.buffer.read()),
            stream_info=stream_info,
            keep_data_uris=args.keep_data_uris,
        )
    else:
        result = markitdown.convert(
            args.filename, stream_info=stream_info, keep_data_uris=args.keep_data_uris
        )

    _handle_output(args, result)


def _filesystem_is_case_insensitive(directory: str) -> bool:
    """Probe whether `directory`'s actual filesystem treats file names that
    differ only by case as the same file.

    This checks the real filesystem rather than assuming behavior from the
    OS name: the default is case-insensitive on Windows and on macOS's
    usual APFS/HFS+, and case-sensitive on most Linux filesystems -- but
    any of those OSes can also be pointed at a directory backed by the
    other kind of filesystem (an exFAT/FAT32-formatted drive, an SMB/CIFS
    share, a case-sensitive-enabled NTFS folder on modern Windows, etc.),
    so relying on the OS name alone would both over- and under-detect.

    The probe creates a single, uniquely-named empty file directly inside
    `directory`, checks whether an upper-cased variant of that same name
    resolves to it too, and removes it again -- it never reads, creates,
    or removes any other file, so pre-existing files (including ones
    already scheduled for conversion) are never touched. On any failure
    (directory not writable, a permissions error, etc.) this conservatively
    returns False, i.e. "assume case-sensitive, do not fold case" -- which
    only means an unlikely, environment-specific collision might be missed
    if the probe itself couldn't run, never that two genuinely distinct
    files get incorrectly treated as colliding.
    """
    probe_name = f".markitdown-case-probe-{uuid.uuid4().hex}"
    probe_path = os.path.join(directory, probe_name)
    variant_path = os.path.join(directory, probe_name.upper())
    if probe_path == variant_path:
        # Not reachable in practice (the ".markitdown-case-probe-" prefix
        # always supplies letters for upper() to change), but avoid ever
        # comparing a path against itself and calling that "insensitive".
        return False

    try:
        fd = os.open(probe_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except OSError:
        return False

    try:
        return os.path.exists(variant_path) and os.path.samefile(
            probe_path, variant_path
        )
    except OSError:
        return False
    finally:
        try:
            os.remove(probe_path)
        except OSError:
            pass


def _normalize_path(path: str, fold_case: bool = False) -> str:
    """Normalize a path for equality/collision comparisons.

    Resolves symlinks and '..'/'.' segments (realpath, which is safe to
    call on paths that don't exist yet), applies Python's own case-folding
    (normcase, which is a real case fold on Windows and a no-op on POSIX),
    and additionally folds case when the caller has determined -- e.g. via
    _filesystem_is_case_insensitive on the actual output directory -- that
    doing so matches the real filesystem's own behavior. Without fold_case,
    this matches paths the way the OS's own path-comparison conventions
    would (case-insensitively on Windows, case-sensitively elsewhere).
    """
    normalized = os.path.normcase(os.path.realpath(path))
    if fold_case:
        normalized = normalized.lower()
    return normalized


def _iter_input_files(
    input_dir: str, recursive: bool, exclude_dir: str, fold_case: bool
) -> List[Tuple[str, str]]:
    """Return (absolute_path, path_relative_to_input_dir) for files under input_dir.

    exclude_dir (e.g. the output directory) is pruned from the walk so that
    output files -- whether written by a previous run or created earlier in
    this same run -- are never picked back up as input. fold_case is passed
    straight through to _normalize_path for that comparison.
    """
    norm_exclude_dir = _normalize_path(exclude_dir, fold_case)
    results = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(input_dir):
            dirnames[:] = [
                d
                for d in dirnames
                if _normalize_path(os.path.join(dirpath, d), fold_case)
                != norm_exclude_dir
            ]
            for filename in sorted(filenames):
                full_path = os.path.join(dirpath, filename)
                results.append((full_path, os.path.relpath(full_path, input_dir)))
    else:
        for entry in sorted(os.listdir(input_dir)):
            full_path = os.path.join(input_dir, entry)
            if os.path.isfile(full_path):
                results.append((full_path, entry))
    return results


def _build_conversion_plan(
    input_dir: str, output_dir: str, recursive: bool, fold_case: bool
) -> List[Tuple[str, str]]:
    """Pair up input files with their planned .md output path.

    If two or more distinct input files would map to the same output path,
    conversion is aborted before anything is written: partially overwriting
    one of them and not the other, depending on processing order, would be
    surprising and hard to detect. A file that is already its own output
    (an existing .md file sitting where it would be "converted" to) is not
    counted here -- it is a no-op, handled later in _convert_directory -- so
    that an existing .md file does not itself register as a false collision.

    fold_case should reflect whether output_dir's actual filesystem treats
    case-differing names as the same file (see
    _filesystem_is_case_insensitive); it decides whether e.g. Report.md and
    report.md are treated as one output path or two here.
    """
    plan = []
    # normalized output path -> (display output path, [input paths])
    by_output: Dict[str, Tuple[str, List[str]]] = {}
    for input_path, rel_path in _iter_input_files(
        input_dir, recursive, output_dir, fold_case
    ):
        rel_md_path = os.path.splitext(rel_path)[0] + ".md"
        output_path = os.path.join(output_dir, rel_md_path)
        plan.append((input_path, output_path))

        if _normalize_path(input_path, fold_case) == _normalize_path(
            output_path, fold_case
        ):
            continue

        key = _normalize_path(output_path, fold_case)
        display_path, inputs = by_output.get(key, (output_path, []))
        inputs.append(input_path)
        by_output[key] = (display_path, inputs)

    collisions = {key: value for key, value in by_output.items() if len(value[1]) > 1}
    if collisions:
        lines = [
            "Refusing to convert: multiple input files would be written to the "
            "same output file. No files were converted. Rename the inputs, "
            "move them into separate folders, or convert them separately.",
        ]
        for display_path, inputs in collisions.values():
            lines.append(f"  {display_path}")
            for input_path in inputs:
                lines.append(f"    <- {input_path}")
        _exit_with_error("\n".join(lines))

    return plan


def _atomic_write(path: str, content: str) -> None:
    """Write content to path, avoiding a partially-written file on failure."""
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".markitdown-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _convert_directory(markitdown: MarkItDown, args) -> None:
    """Convert every file in args.filename (a directory) to a .md file."""
    input_dir = args.filename
    output_dir = args.output if args.output else input_dir

    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        _exit_with_error(f"Could not create output directory {output_dir}: {e}")

    # Determine once, against the real output filesystem, whether names
    # differing only by case refer to the same file there -- rather than
    # assuming that from the OS -- and use that consistently for every
    # path comparison below (collision detection, self-output detection,
    # and the recursive output-directory exclusion in _iter_input_files).
    fold_case = _filesystem_is_case_insensitive(output_dir)

    plan = _build_conversion_plan(input_dir, output_dir, args.recursive, fold_case)

    converted = 0
    failed = 0
    skipped = 0
    for input_path, output_path in plan:
        if _normalize_path(input_path, fold_case) == _normalize_path(
            output_path, fold_case
        ):
            # Input file is already the intended output (e.g., converting a
            # folder that already contains .md files, in place). Since the
            # collision check above guarantees no other input targets this
            # same output path, it is safe to leave it untouched.
            skipped += 1
            continue

        if os.path.exists(output_path) and not args.overwrite:
            print(
                f"[SKIPPED] {input_path}: output file already exists: "
                f"{output_path} (use --overwrite to replace it)",
                file=sys.stderr,
            )
            failed += 1
            continue

        try:
            result = markitdown.convert(input_path, keep_data_uris=args.keep_data_uris)
        except Exception as e:
            print(f"[SKIPPED] {input_path}: conversion failed: {e}", file=sys.stderr)
            failed += 1
            continue

        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            _atomic_write(output_path, result.markdown)
        except OSError as e:
            print(
                f"[SKIPPED] {input_path}: failed to write {output_path}: {e}",
                file=sys.stderr,
            )
            failed += 1
            continue

        print(f"{input_path} -> {output_path}")
        converted += 1

    print(
        f"\nConverted {converted} file(s), {failed} failed, {skipped} skipped "
        "(already up to date).",
        file=sys.stderr,
    )
    if failed > 0:
        sys.exit(1)


def _handle_output(args, result: DocumentConverterResult):
    """Handle output to stdout or file"""
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result.markdown)
    else:
        # Handle stdout encoding errors more gracefully
        print(
            result.markdown.encode(sys.stdout.encoding, errors="replace").decode(
                sys.stdout.encoding
            )
        )


def _exit_with_error(message: str):
    print(message)
    sys.exit(1)


if __name__ == "__main__":
    main()
