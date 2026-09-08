#!/usr/bin/env python3 -m pytest
import io
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

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
    # real collision is now determined by actually probing tmp_path's
    # filesystem (_filesystem_is_case_insensitive), not by assuming it from
    # the OS name. This test still branches on sys.platform because it
    # can't control which filesystem CI actually mounts tmp_path on -- but
    # it's asserting against each platform's typical default filesystem
    # (NTFS on Windows, APFS/HFS+ on macOS: both case-insensitive by
    # default; most Linux filesystems: case-sensitive), which the probe is
    # now expected to detect correctly on all three, including macOS --
    # previously a blind spot documented as undetectable. See
    # test_filesystem_is_case_insensitive_* below for platform-independent
    # coverage of the probe itself and of the collision-detection wiring
    # that consumes it.
    (tmp_path / "Report.PDF").write_text("dummy pdf content")
    (tmp_path / "report.pdf").write_text("dummy pdf content")

    result = subprocess.run(
        [sys.executable, "-m", "markitdown", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    if sys.platform.startswith("win") or sys.platform == "darwin":
        assert result.returncode != 0
        combined_output = result.stdout + result.stderr
        assert "Report.md" in combined_output or "report.md" in combined_output
    else:
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert (tmp_path / "Report.md").exists()
        assert (tmp_path / "report.md").exists()


def test_filesystem_is_case_insensitive_probe_on_this_platform(tmp_path) -> None:
    # Exercises the real probe (real os.open/os.path.exists/os.path.samefile
    # calls) against tmp_path's actual filesystem. This project's CI only
    # runs on ubuntu-latest, whose usual filesystem (ext4, or overlayfs on
    # top of it in a container) is case-sensitive, so that's the only
    # branch actually exercised there; this is not verified against a real
    # case-insensitive filesystem (default macOS, or Windows) by this test
    # suite -- see test_filesystem_is_case_insensitive_forced_true below for
    # how that branch is covered instead, by simulating the probe's result
    # rather than by mounting a case-insensitive filesystem.
    from markitdown.__main__ import _filesystem_is_case_insensitive

    if sys.platform.startswith("win") or sys.platform == "darwin":
        pytest.skip(
            "This assertion targets Linux's typical case-sensitive default; "
            "Windows/macOS are covered by the platform branch in "
            "test_directory_conversion_case_only_names_on_this_platform."
        )
    assert _filesystem_is_case_insensitive(str(tmp_path)) is False
    # The probe must not leave its temporary file behind, success or not.
    assert list(tmp_path.iterdir()) == []


def test_filesystem_is_case_insensitive_raises_when_probe_cannot_run(
    tmp_path, monkeypatch
) -> None:
    # The probe must surface "I couldn't check" as a distinct outcome
    # (raising) rather than collapsing it into "checked, and it's
    # case-sensitive" (returning False) -- the caller decides what "unknown"
    # means, instead of that ambiguity being baked into the return value.
    from markitdown.__main__ import _filesystem_is_case_insensitive

    def _raise(*args, **kwargs):
        raise OSError("simulated: directory not writable")

    monkeypatch.setattr(os, "open", _raise)
    with pytest.raises(OSError):
        _filesystem_is_case_insensitive(str(tmp_path))
    # os.open itself failed, so there is nothing to have created or left
    # behind.
    assert list(tmp_path.iterdir()) == []


def test_filesystem_is_case_insensitive_cleans_up_probe_file_on_failure(
    tmp_path, monkeypatch
) -> None:
    # If a later step in the probe (after the temp file was created) fails
    # unexpectedly, the temp file must still be removed and the failure
    # must still propagate rather than being swallowed into False.
    from markitdown.__main__ import _filesystem_is_case_insensitive

    def _raise(*args, **kwargs):
        raise OSError("simulated: samefile failed unexpectedly")

    monkeypatch.setattr(os.path, "exists", lambda path: True)
    monkeypatch.setattr(os.path, "samefile", _raise)
    with pytest.raises(OSError):
        _filesystem_is_case_insensitive(str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_filesystem_is_case_insensitive_forced_true(tmp_path, monkeypatch) -> None:
    # Simulates what the probe would report on a real case-insensitive
    # filesystem (default macOS, or Windows), without needing one: makes
    # os.path.exists/os.path.samefile agree that the upper-cased variant of
    # the probe file resolves to the same file, exactly as they would on
    # such a filesystem, and confirms the probe reports that faithfully.
    from markitdown.__main__ import _filesystem_is_case_insensitive

    monkeypatch.setattr(os.path, "exists", lambda path: True)
    monkeypatch.setattr(os.path, "samefile", lambda a, b: True)
    assert _filesystem_is_case_insensitive(str(tmp_path)) is True
    assert list(tmp_path.iterdir()) == []


def test_directory_conversion_collision_when_filesystem_is_case_insensitive(
    tmp_path, monkeypatch, capsys
) -> None:
    # End-to-end wiring check for the case-insensitive branch: forces
    # _filesystem_is_case_insensitive to report True (as it would on a real
    # case-insensitive filesystem) and confirms that Report.PDF and
    # report.pdf are then correctly refused as a collision by the full CLI
    # path, in-process, on this sandbox's actual (case-sensitive) Linux
    # filesystem. This isolates "does the rest of the collision-detection
    # logic react correctly to fold_case=True" from "does the probe itself
    # correctly detect a real case-insensitive filesystem" (covered
    # separately, and only on Linux, by
    # test_filesystem_is_case_insensitive_probe_on_this_platform).
    import markitdown.__main__ as md_main

    (tmp_path / "Report.PDF").write_text("dummy pdf content")
    (tmp_path / "report.pdf").write_text("dummy pdf content")

    monkeypatch.setattr(md_main, "_filesystem_is_case_insensitive", lambda d: True)
    monkeypatch.setattr(sys, "argv", ["markitdown", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        md_main.main()
    assert exc_info.value.code != 0

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert "Report.md" in combined_output or "report.md" in combined_output
    assert not (tmp_path / "Report.md").exists()
    assert not (tmp_path / "report.md").exists()


def test_directory_conversion_aborts_when_case_probe_fails(
    tmp_path, monkeypatch, capsys
) -> None:
    # If the case-sensitivity probe can't be carried out at all, the batch
    # must refuse to convert -- not proceed as if the filesystem were
    # case-sensitive, which is exactly the assumption that could let two
    # case-differing inputs silently overwrite each other's output.
    import markitdown.__main__ as md_main

    (tmp_path / "a.html").write_text("<html><body><h1>Hello</h1></body></html>")
    (tmp_path / "a.md").write_text("pre-existing content, must survive")

    def _raise(*args, **kwargs):
        raise OSError("simulated: directory not writable")

    monkeypatch.setattr(md_main, "_filesystem_is_case_insensitive", _raise)
    monkeypatch.setattr(sys, "argv", ["markitdown", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        md_main.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    # Names the output directory that couldn't be checked, and the reason.
    assert str(tmp_path) in combined_output
    assert "simulated: directory not writable" in combined_output

    # Nothing was converted, and the pre-existing a.md was left untouched.
    assert (tmp_path / "a.md").read_text() == "pre-existing content, must survive"
    assert not (tmp_path / "Report.md").exists()


def test_directory_conversion_aborts_when_case_probe_fails_subprocess(
    tmp_path,
) -> None:
    # Same as test_directory_conversion_aborts_when_case_probe_fails, but
    # via a real subprocess with a genuinely unwritable output directory
    # (rather than a monkeypatched failure), so this doesn't rely on
    # in-process monkeypatching to prove the CLI actually refuses to guess.
    # Skipped when running as root, since root can write through the
    # read-only permission bit this test relies on to make os.open fail.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root can bypass the read-only permission bit this test relies on")

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    (input_dir / "a.html").write_text("<html><body><h1>Hello</h1></body></html>")

    output_dir.chmod(0o500)  # read + execute, no write
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "markitdown",
                str(input_dir),
                "-o",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
        )
    finally:
        output_dir.chmod(0o700)

    assert result.returncode == 1
    assert not (output_dir / "a.md").exists()


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


def test_normalize_path_fold_case_parameter(tmp_path) -> None:
    # _normalize_path's fold_case parameter is the primary, filesystem-
    # probe-driven case-folding mechanism (normcase above is a secondary,
    # OS-name-based effect layered on top of it). This checks fold_case
    # directly, independent of the current OS's own normcase behavior.
    from markitdown.__main__ import _normalize_path

    a = str(tmp_path / "Report.md")
    b = str(tmp_path / "report.md")

    assert _normalize_path(a, fold_case=True) == _normalize_path(b, fold_case=True)
    assert _normalize_path(a, fold_case=False) != _normalize_path(b, fold_case=False)


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
