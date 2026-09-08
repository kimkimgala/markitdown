#!/usr/bin/env python3 -m pytest
import io
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


def test_directory_conversion_case_insensitive_collision(tmp_path) -> None:
    # On a case-insensitive filesystem (as is typical on Windows), Report.PDF
    # and report.pdf would collide with each other's ".md" output too.
    (tmp_path / "Report.PDF").write_text("dummy pdf content")
    (tmp_path / "report.pdf").write_text("dummy pdf content")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    if sys.platform.startswith("win") or sys.platform == "darwin":
        # On a case-insensitive filesystem, Report.md and report.md are the
        # same path, so both inputs collide on one real output file.
        assert result.returncode != 0
        combined_output = result.stdout + result.stderr
        assert "Report.md" in combined_output or "report.md" in combined_output
    else:
        # On a case-sensitive filesystem, Report.md and report.md are
        # distinct files, so both inputs convert independently.
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"


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
