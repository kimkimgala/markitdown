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


if __name__ == "__main__":
    """Runs this file's tests from the command line."""
    test_version()
    test_invalid_flag()
    print("All tests passed!")
