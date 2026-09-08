#!/usr/bin/env python3 -m pytest
import io
import os
import subprocess
import sys
from types import SimpleNamespace

from markitdown import __version__
from markitdown.__main__ import main

# This file contains CLI tests that are not directly tested by the FileTestVectors.
# This includes things like help messages, version numbers, and invalid flags.


def test_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "markitdown", "--version"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
    assert __version__ in result.stdout, f"Version not found in output: {result.stdout}"


def test_invalid_flag() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "markitdown", "--foobar"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, f"CLI exited with error: {result.stderr}"
    assert (
        "unrecognized arguments" in result.stderr
    ), "Expected 'unrecognized arguments' to appear in STDERR"
    assert "SYNTAX" in result.stderr, "Expected 'SYNTAX' to appear in STDERR"


def test_windows_pipe_input_is_buffered_before_conversion(monkeypatch, capsys) -> None:
    class WindowsPipe(io.BytesIO):
        def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
            if whence == io.SEEK_END:
                return super().seek(offset, whence)
            return 0

    stdin = SimpleNamespace(
        buffer=WindowsPipe(b"<html><body><h1>Test HTML</h1></body></html>")
    )
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "argv", ["markitdown", "-x", "html"])

    main()

    captured = capsys.readouterr()
    assert captured.out.strip() == "# Test HTML"


def test_directory_conversion_in_place(tmp_path) -> None:
    (tmp_path / "a.html").write_text("<html><body><h1>Hello</h1></body></html>")
    (tmp_path / "b.txt").write_text("plain text")
    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()
    (sub_dir / "c.html").write_text("<html><body><h2>Sub</h2></body></html>")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
    assert (tmp_path / "a.md").read_text().strip() == "# Hello"
    assert (tmp_path / "b.md").exists()
    # Non-recursive: files in subdirectories are left untouched.
    assert not (sub_dir / "c.md").exists()


def test_directory_conversion_recursive_to_output_dir(tmp_path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    sub_dir = input_dir / "sub"
    sub_dir.mkdir(parents=True)
    (input_dir / "a.html").write_text("<html><body><h1>Hello</h1></body></html>")
    (sub_dir / "b.html").write_text("<html><body><h2>Sub</h2></body></html>")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "markitdown",
            str(input_dir),
            "-o",
            str(output_dir),
            "-r",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
    assert (output_dir / "a.md").read_text().strip() == "# Hello"
    assert (output_dir / "sub" / "b.md").read_text().strip() == "## Sub"
    # Original files are untouched.
    assert (input_dir / "a.html").exists()


def test_directory_conversion_skips_unconvertible_files(tmp_path) -> None:
    (tmp_path / "a.html").write_text("<html><body><h1>Hello</h1></body></html>")
    # A binary file with an unrecognized/unsupported extension.
    (tmp_path / "b.bin").write_bytes(bytes(range(256)))

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    # One file failed to convert, so the CLI reports a non-zero exit code,
    # but the file that could be converted still succeeded.
    assert result.returncode != 0
    assert (tmp_path / "a.md").exists()
    assert not (tmp_path / "b.md").exists()
    assert "SKIPPED" in result.stderr


def test_directory_conversion_empty_folder(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
    assert list(tmp_path.iterdir()) == []


def test_directory_conversion_aborts_on_output_collision(tmp_path) -> None:
    # report.pdf and report.docx would both convert to report.md.
    (tmp_path / "report.pdf").write_text("dummy pdf content")
    (tmp_path / "report.docx").write_text("dummy docx content")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    # Nothing should have been converted: the collision is caught up front.
    assert not (tmp_path / "report.md").exists()
    combined_output = result.stdout + result.stderr
    assert "report.pdf" in combined_output
    assert "report.docx" in combined_output
    assert "report.md" in combined_output


def test_directory_conversion_collision_detected_even_with_overwrite(tmp_path) -> None:
    # report.pdf and report.docx both target report.md, which also already
    # exists on disk. Even with --overwrite, this must still be reported as
    # a collision between two different inputs rather than silently letting
    # one of them win: --overwrite only controls replacing an existing file
    # for a *single* input, not picking a winner between competing inputs.
    (tmp_path / "report.pdf").write_text("dummy pdf content")
    (tmp_path / "report.docx").write_text("dummy docx content")
    (tmp_path / "report.md").write_text("pre-existing content, must survive")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path), "--overwrite"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (tmp_path / "report.md").read_text() == "pre-existing content, must survive"
    combined_output = result.stdout + result.stderr
    assert "report.pdf" in combined_output
    assert "report.docx" in combined_output


def test_directory_conversion_existing_markdown_protected_from_other_input(
    tmp_path,
) -> None:
    # A single input (report.pdf) whose target (report.md) already exists
    # is the "protect existing output" case, not a collision: only one
    # input is competing for that output path, so the fix is --overwrite,
    # not renaming files.
    (tmp_path / "report.pdf").write_text("dummy pdf content")
    (tmp_path / "report.md").write_text("hand-written report, must survive")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (tmp_path / "report.md").read_text() == "hand-written report, must survive"
    assert "SKIPPED" in result.stderr
    assert "already exists" in result.stderr


def test_directory_conversion_existing_markdown_replaced_with_overwrite(
    tmp_path,
) -> None:
    (tmp_path / "report.pdf").write_text("dummy pdf content")
    (tmp_path / "report.md").write_text("stale content, should be replaced")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path), "--overwrite"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
    assert (tmp_path / "report.md").read_text() == "dummy pdf content"


def test_directory_conversion_case_only_names_on_this_platform(tmp_path) -> None:
    # Report.PDF and report.pdf would both produce a ".md" output that
    # differs only in case ("Report.md" vs "report.md"). Whether that's a
    # real collision depends on the platform actually running this test:
    # Python's os.path.normcase() -- which the collision check relies on --
    # is documented to fold case only on Windows, so this pre-flight check
    # only ever treats the two as colliding there. On every other platform
    # (including this test's own, when run on Linux or macOS CI), the check
    # sees them as distinct and lets both convert. See
    # test_normalize_path_folds_case_only_like_windows_would below for a
    # platform-independent check of that same normcase-based logic, and the
    # README's "Batch-Converting a Folder" section for what this means in
    # practice on a case-insensitive filesystem such as default macOS.
    (tmp_path / "Report.PDF").write_text("dummy pdf content")
    (tmp_path / "report.pdf").write_text("dummy pdf content")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    if sys.platform.startswith("win"):
        assert result.returncode != 0
        combined_output = result.stdout + result.stderr
        assert "Report.md" in combined_output or "report.md" in combined_output
    else:
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert (tmp_path / "Report.md").exists()
        assert (tmp_path / "report.md").exists()


def test_normalize_path_folds_case_only_like_windows_would(
    monkeypatch, tmp_path
) -> None:
    # Exercise the actual case-folding behavior the collision check relies
    # on without needing a real Windows machine: os.path.normcase() folds
    # case only on Windows (ntpath.normcase), and is a documented no-op
    # everywhere else (posixpath.normcase). This asserts that contract
    # directly, on whatever OS is running the test.
    #
    # os.path *is* posixpath (or ntpath) -- the very same module object, not
    # a copy -- so patching os.path.normcase also mutates posixpath.normcase
    # itself. The original function reference is captured up front, before
    # any patching, so the "no-op on POSIX" assertion below isn't checking
    # against an already-patched function.
    import ntpath

    from markitdown.__main__ import _normalize_path

    original_normcase = os.path.normcase
    a = str(tmp_path / "Report.md")
    b = str(tmp_path / "report.md")

    assert original_normcase(a) != original_normcase(b), (
        "this test assumes it runs on a platform (e.g. Linux CI) where "
        "os.path.normcase is the documented POSIX no-op"
    )
    assert _normalize_path(a) != _normalize_path(b), (
        "posixpath.normcase is documented as a no-op, so on POSIX this "
        "check must NOT treat case-only-differing paths as equal"
    )

    monkeypatch.setattr(os.path, "normcase", ntpath.normcase)
    assert _normalize_path(a) == _normalize_path(b), (
        "normcase is documented to fold case on Windows, so the collision "
        "check must treat case-only-differing paths as equal there"
    )


def test_directory_conversion_default_does_not_overwrite(tmp_path) -> None:
    (tmp_path / "a.html").write_text("<html><body><h1>Hello</h1></body></html>")
    (tmp_path / "a.md").write_text("pre-existing content, must survive")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (tmp_path / "a.md").read_text() == "pre-existing content, must survive"
    assert "SKIPPED" in result.stderr
    assert "already exists" in result.stderr


def test_directory_conversion_overwrite_flag_replaces_existing(tmp_path) -> None:
    (tmp_path / "a.html").write_text("<html><body><h1>Hello</h1></body></html>")
    (tmp_path / "a.md").write_text("stale content, should be replaced")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path), "--overwrite"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
    assert (tmp_path / "a.md").read_text().strip() == "# Hello"


def test_directory_conversion_rerun_is_stable(tmp_path) -> None:
    (tmp_path / "a.html").write_text("<html><body><h1>Hello</h1></body></html>")

    first = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, f"CLI exited with error: {first.stderr}"
    assert (tmp_path / "a.md").read_text().strip() == "# Hello"

    # Re-running without --overwrite must not touch the .md file, and
    # crucially must not treat a.md as a new input file to convert either.
    second = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert second.returncode != 0  # a.md already exists, skipped -> failed count
    assert (tmp_path / "a.md").read_text().strip() == "# Hello"
    assert "SKIPPED" in second.stderr


def test_directory_conversion_write_error_continues_and_reports(tmp_path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    (input_dir / "sub").mkdir(parents=True)
    (input_dir / "sub" / "a.html").write_text(
        "<html><body><h1>Hello</h1></body></html>"
    )
    (input_dir / "ok.html").write_text("<html><body><h1>OK</h1></body></html>")

    output_dir.mkdir()
    # Create a *file* named "sub" inside the output directory, so that
    # creating the "sub" output subdirectory for sub/a.html fails.
    (output_dir / "sub").write_text("I am a file, not a directory")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "markitdown",
            str(input_dir),
            "-o",
            str(output_dir),
            "-r",
        ],
        capture_output=True,
        text=True,
    )

    # The failing file should not stop the other file from being converted.
    assert result.returncode != 0
    assert (output_dir / "ok.md").read_text().strip() == "# OK"
    assert not (output_dir / "sub" / "a.md").exists()
    assert "SKIPPED" in result.stderr


def test_directory_conversion_output_dir_inside_input_dir_not_reconverted(
    tmp_path,
) -> None:
    input_dir = tmp_path
    output_dir = tmp_path / "converted"
    (input_dir / "a.html").write_text("<html><body><h1>Hello</h1></body></html>")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "markitdown",
            str(input_dir),
            "-o",
            str(output_dir),
            "-r",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
    assert (output_dir / "a.md").read_text().strip() == "# Hello"
    # The freshly-written output/a.md must not have been picked back up and
    # converted again into output/converted/a.md.
    assert not (output_dir / "converted").exists()


def test_directory_conversion_existing_markdown_not_self_overwritten(
    tmp_path,
) -> None:
    (tmp_path / "already.md").write_text("# Already markdown\n")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
    assert (tmp_path / "already.md").read_text() == "# Already markdown\n"


def test_single_file_conversion_still_overwrites_without_flag(tmp_path) -> None:
    # The batch --overwrite protection must not affect single-file mode.
    src = tmp_path / "a.html"
    src.write_text("<html><body><h1>Hello</h1></body></html>")
    dest = tmp_path / "out.md"
    dest.write_text("stale content")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(src), "-o", str(dest)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
    assert dest.read_text().strip() == "# Hello"


def test_stdin_conversion_still_works(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "markitdown"],
        input="<html><body><h1>Hello</h1></body></html>",
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
    assert result.stdout.strip() == "# Hello"


if __name__ == "__main__":
    """Runs this file's tests from the command line."""
    test_version()
    test_invalid_flag()
    print("All tests passed!")
