# MarkItDown

[![PyPI](https://img.shields.io/pypi/v/markitdown.svg)](https://pypi.org/project/markitdown/)
![PyPI - Downloads](https://img.shields.io/pypi/dd/markitdown)

> [!IMPORTANT]
> MarkItDown performs I/O with the privileges of the current process. Like open() or requests.get(), it will access resources that the process itself can access. Sanitize your inputs in untrusted environments, and call the narrowest `convert_*` function needed for your use case (e.g., `convert_stream()`, or `convert_local()`). See the [Security Considerations](#security-considerations) section of the documentation for more information.

MarkItDown is a lightweight Python utility for converting various files to Markdown for use with LLMs and related text analysis pipelines. To this end, it is most comparable to [textract](https://github.com/deanmalmgren/textract), but with a focus on preserving important document structure and content as Markdown (including: headings, lists, tables, links, etc.) While the output is often reasonably presentable and human-friendly, it is meant to be consumed by text analysis tools -- and may not be the best option for high-fidelity document conversions for human consumption.

MarkItDown currently supports the conversion from:

- PDF
- PowerPoint
- Word
- Excel
- Images (EXIF metadata and OCR)
- Audio (EXIF metadata and speech transcription)
- HTML
- Text-based formats (CSV, JSON, XML)
- ZIP files (iterates over contents)
- YouTube URLs
- EPubs
- ... and more!

## Why Markdown?

Markdown is extremely close to plain text, with minimal markup or formatting, but still
provides a way to represent important document structure. Mainstream LLMs, such as
OpenAI's GPT-4o, natively "_speak_" Markdown, and often incorporate Markdown into their
responses unprompted. This suggests that they have been trained on vast amounts of
Markdown-formatted text, and understand it well. As a side benefit, Markdown conventions
are also highly token-efficient.

## Prerequisites
MarkItDown requires Python 3.10 or higher. It is recommended to use a virtual environment to avoid dependency conflicts.

With the standard Python installation, you can create and activate a virtual environment using the following commands:

```bash
python -m venv .venv
source .venv/bin/activate
```

If using `uv`, you can create a virtual environment with:

```bash
uv venv --python=3.12 .venv
source .venv/bin/activate
# NOTE: Be sure to use 'uv pip install' rather than just 'pip install' to install packages in this virtual environment
```

If you are using Anaconda, you can create a virtual environment with:

```bash
conda create -n markitdown python=3.12
conda activate markitdown
```

## Installation

To install MarkItDown, use pip: `pip install 'markitdown[all]'`. Alternatively, you can install it from the source:

```bash
git clone git@github.com:microsoft/markitdown.git
cd markitdown
pip install -e 'packages/markitdown[all]'
```

## Usage

### Command-Line

```bash
markitdown path-to-file.pdf > document.md
```

Or use `-o` to specify the output file:

```bash
markitdown path-to-file.pdf -o document.md
```

You can also pipe content:

```bash
cat path-to-file.pdf | markitdown
```

### Batch-Converting a Folder

If you pass a folder instead of a file, every file directly inside it is converted to a `.md` file with the same base name:

```bash
markitdown path-to-folder
```

By default, the `.md` files are written next to the originals. Use `-o` to write them to a different folder instead, and add `-r`/`--recursive` to also convert files in subfolders (subfolder structure is preserved in the output folder):

```bash
markitdown path-to-folder -o path-to-output-folder -r
```

**Safety behavior of folder conversion:**

* **Output collisions between different input files abort the whole batch, even with `--overwrite`.** Before converting anything, markitdown checks whether two or more *different* input files would produce the same output path (e.g. `report.pdf` and `report.docx` both becoming `report.md`). If so, it exits with an error listing the conflicting files and converts nothing — it never guesses which one should "win", and `--overwrite` does not bypass this check, since it exists to control overwriting existing files on disk, not to pick a winner between two inputs racing for the same name. Rename the files, put them in separate folders, or convert them separately instead.
* **An existing output file is protected by default, `--overwrite` replaces it.** If `report.md` already exists (from a previous run, or just because it was already there) and `report.pdf` is the only input that would produce `report.md`, converting it is skipped with a message on stderr unless `--overwrite` is passed, so re-running the same command is safe by default and won't clobber prior output or hand-edited files. This is a single-input-vs-existing-file check and is independent from the collision check above: an existing `report.md` sitting alongside *both* `report.pdf` and `report.docx` still hits the collision error first, `--overwrite` or not, because at that point there are two candidate inputs, not one.
* **An existing `.md` file that is itself one of the scanned inputs is left alone, not treated as a self-overwrite.** Every file in the folder is scanned, including `.md` files, but converting a Markdown file to Markdown would just write it to itself, so that specific input is always a no-op — it's neither an error nor does it count against another input as a collision by itself (see the point above: it only turns into a collision once a *second, different* input also targets that same path).
* **Case-only name collisions (e.g. `Report.md` vs. `report.md`) are detected by checking the real output folder, not by assuming behavior from the OS.** Before converting, markitdown creates one uniquely-named, empty temporary file inside the output folder, checks whether an upper-cased variant of that same name resolves back to it, and removes it again — this never reads, creates, or removes any other file. If the output folder's actual filesystem treats case-differing names as the same file (the default on Windows and on macOS's usual APFS/HFS+, but also possible on Linux for a FAT/exFAT-formatted drive or an SMB/CIFS mount, and *not* guaranteed on Windows or macOS either if the folder is on a filesystem configured otherwise), `Report.md` and `report.md` are treated as one output path and a genuine collision between two differently-cased inputs is caught up front like any other. On the usual case-sensitive Linux filesystems, they're correctly left as two independent, unrelated outputs instead. If this probe itself can't run (e.g. the output folder isn't writable), markitdown conservatively falls back to *not* folding case for that run, matching this feature's original Windows-only behavior, rather than failing the whole batch over it.
  * This has been validated on Linux (this project's CI target): both the real probe against the real filesystem, and — by simulating the probe's result — the collision logic that consumes it. The equivalent behavior on a real case-insensitive filesystem (default macOS, or Windows) has not been exercised against actual hardware by this project's test suite; it has only been reasoned about from how `os.open`, `os.path.exists`, and `os.path.samefile` are documented to behave there, and indirectly exercised through the same simulated-result tests.
* **Files that fail to convert are skipped**, not fatal: a message naming the file and the error is printed to stderr, and the rest of the batch continues.
* **The process exits with status `1`** if any file was skipped due to a conversion error or an existing output file (with `--overwrite` not passed); it exits `0` only if every file converted (or was correctly left alone as a no-op).
* If `-o` points to a folder nested inside the input folder, that output folder is excluded from the scan, so freshly written `.md` files are never picked back up and converted again in the same run.
* **The "protect existing files by default" behavior is a single-process, not-guaranteed-atomic check.** Each file is written via a temp-file-then-rename so a crash mid-write can't leave a half-written `.md` file, but the "does the output already exist?" check and that write are not combined into one atomic operation. Running two `markitdown` processes against the same output folder at the same time can still result in one process's output silently replacing the other's, regardless of `--overwrite`. This tool does not implement cross-process locking; avoid running concurrent batch conversions against the same output folder.

None of the above applies to single-file conversion (`markitdown file.pdf -o out.md`) or stdin conversion, which keep their original behavior of always writing/overwriting the given output.

### Optional Dependencies
MarkItDown has optional dependencies for activating various file formats. Earlier in this document, we installed all optional dependencies with the `[all]` option. However, you can also install them individually for more control. For example:

```bash
pip install 'markitdown[pdf, docx, pptx]'
```

will install only the dependencies for PDF, DOCX, and PPTX files.

At the moment, the following optional dependencies are available:

* `[all]` Installs all optional dependencies
* `[pptx]` Installs dependencies for PowerPoint files
* `[docx]` Installs dependencies for Word files
* `[xlsx]` Installs dependencies for Excel files
* `[xls]` Installs dependencies for older Excel files
* `[pdf]` Installs dependencies for PDF files
* `[outlook]` Installs dependencies for Outlook messages
* `[az-doc-intel]` Installs dependencies for Azure Document Intelligence
* `[az-content-understanding]` Installs dependencies for Azure Content Understanding
* `[audio-transcription]` Installs dependencies for audio transcription of wav and mp3 files
* `[youtube-transcription]` Installs dependencies for fetching YouTube video transcription

### Plugins

MarkItDown also supports 3rd-party plugins. Plugins are disabled by default. To list installed plugins:

```bash
markitdown --list-plugins
```

To enable plugins use:

```bash
markitdown --use-plugins path-to-file.pdf
```

To find available plugins, search GitHub for the hashtag `#markitdown-plugin`. To develop a plugin, see `packages/markitdown-sample-plugin`.

#### markitdown-ocr Plugin

The `markitdown-ocr` plugin adds OCR support to PDF, DOCX, PPTX, and XLSX converters, extracting text from embedded images using LLM Vision — the same `llm_client` / `llm_model` pattern that MarkItDown already uses for image descriptions. No new ML libraries or binary dependencies required.

**Installation:**

```bash
pip install markitdown-ocr
pip install openai  # or any OpenAI-compatible client
```

**Usage:**

Pass the same `llm_client` and `llm_model` you would use for image descriptions:

```python
from markitdown import MarkItDown
from openai import OpenAI

md = MarkItDown(
    enable_plugins=True,
    llm_client=OpenAI(),
    llm_model="gpt-4o",
)
result = md.convert("document_with_images.pdf")
print(result.markdown)
```

If no `llm_client` is provided the plugin still loads, but OCR is silently skipped and the standard built-in converter is used instead.

See [`packages/markitdown-ocr/README.md`](packages/markitdown-ocr/README.md) for detailed documentation.

### Azure Content Understanding

[Azure Content Understanding](https://learn.microsoft.com/azure/ai-services/content-understanding/) provides higher-quality conversion with structured field extraction (YAML front matter), multi-modal support (documents, images, audio, video), and configurable analyzers.

Install: `pip install 'markitdown[az-content-understanding]'`

#### When to use Content Understanding

Content Understanding is ideal when you need capabilities beyond what built-in or Document Intelligence converters provide:

- **Audio and video files** — CU is the only option for video, and the higher-quality cloud option for audio. Built-in converters have no video support and only basic audio transcription.
- **Structured field extraction** — [Prebuilt](https://learn.microsoft.com/azure/ai-services/content-understanding/concepts/prebuilt-analyzers) or [custom-built](https://learn.microsoft.com/azure/ai-services/content-understanding/how-to/customize-analyzer-content-understanding-studio?tabs=portal) analyzers extract domain-specific fields (invoice amounts, receipt dates, contract clauses) serialized as YAML front matter. Neither built-in nor Doc Intel integration exposes fields.
- **Higher-quality document extraction** — Cloud-based layout analysis and OCR for scanned PDFs, complex tables, and multi-page documents.
- **Single API for all modalities** — One `cu_endpoint` handles documents, images, audio, and video with automatic analyzer routing.

| Capability | Built-in converters | Azure Document Intelligence | Azure Content Understanding |
|------------|---------------------|-----------------------------|-----------------------------|
| Document conversion | Offline, format-specific extraction | Cloud layout extraction | Cloud multimodal extraction |
| Structured fields | Not available | Not exposed by this integration | YAML front matter from analyzer fields |
| Custom analyzers | Not available | Not configurable in this integration | Supported with `cu_analyzer_id` |
| Audio and video | Basic audio, no video | Not supported | Audio and video analyzers |
| Cost | Local compute only | Billable Azure API calls | Billable Azure API calls |

**CLI:**

```bash
markitdown path-to-file.pdf --use-cu --cu-endpoint "<content_understanding_endpoint>"
```

The endpoint can also be set once in the environment, so callers only need `--use-cu`:

```bash
export MARKITDOWN_CU_ENDPOINT="<content_understanding_endpoint>"
markitdown path-to-file.pdf --use-cu
```

**Python API:**

```python
from markitdown import MarkItDown

# Zero-config — auto-selects analyzer per file type
md = MarkItDown(cu_endpoint="<content_understanding_endpoint>")
result = md.convert("report.pdf")   # documents → prebuilt-documentSearch
result = md.convert("meeting.mp4")  # video → prebuilt-videoSearch
result = md.convert("call.wav")     # audio → prebuilt-audioSearch
print(result.markdown)
```

**With a custom analyzer** (for domain-specific field extraction):

```python
md = MarkItDown(
    cu_endpoint="<content_understanding_endpoint>",
    cu_analyzer_id="my-invoice-analyzer",
)
result = md.convert("invoice.pdf")
print(result.markdown)
# Output includes YAML front matter with extracted fields:
# ---
# contentType: document
# fields:
#   VendorName: CONTOSO LTD.
#   InvoiceDate: '2019-11-15'
# ---
# <!-- page 1 -->
# ...
```

When `cu_analyzer_id` is set, the converter automatically scopes it to compatible file types based on the analyzer's modality. Incompatible types (e.g., audio files with a document analyzer) auto-route to default prebuilt analyzers.

**Cost note:** Each `convert()` call for a CU-routed format is a billable Azure API call. Use `cu_file_types` to restrict which formats route to CU:

```python
from markitdown.converters import ContentUnderstandingFileType

md = MarkItDown(
    cu_endpoint="<content_understanding_endpoint>",
    cu_file_types=[ContentUnderstandingFileType.PDF],  # only PDFs use CU
)
```

More information about Azure Content Understanding can be found [here](https://learn.microsoft.com/azure/ai-services/content-understanding/).

### Azure Document Intelligence

To use Microsoft Document Intelligence for conversion:

```bash
markitdown path-to-file.pdf -o document.md -d -e "<document_intelligence_endpoint>"
```

The endpoint can also be set once in the environment, so callers only need `-d`:

```bash
export MARKITDOWN_DOCINTEL_ENDPOINT="<document_intelligence_endpoint>"
markitdown path-to-file.pdf -o document.md -d
```

More information about how to set up an Azure Document Intelligence Resource can be found [here](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/how-to-guides/create-document-intelligence-resource?view=doc-intel-4.0.0)

### Python API

Basic usage in Python:

```python
from markitdown import MarkItDown

md = MarkItDown(enable_plugins=False) # Set to True to enable plugins
result = md.convert("test.xlsx")
print(result.markdown)
```

Document Intelligence conversion in Python:

```python
from markitdown import MarkItDown

md = MarkItDown(docintel_endpoint="<document_intelligence_endpoint>")
result = md.convert("test.pdf")
print(result.markdown)
```

To use Large Language Models for image descriptions (currently only for pptx and image files), provide `llm_client` and `llm_model`:

```python
from markitdown import MarkItDown
from openai import OpenAI

client = OpenAI()
md = MarkItDown(llm_client=client, llm_model="gpt-4o", llm_prompt="optional custom prompt")
result = md.convert("example.jpg")
print(result.markdown)
```

### Docker

```sh
docker build -t markitdown:latest .
docker run --rm -i markitdown:latest < ~/your-file.pdf > output.md
```

## Contributing

Before starting significant work, please read [What to Contribute](#what-to-contribute), which describes what is in and out of scope for this repository.

This project welcomes contributions and suggestions. Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

### What to Contribute

MarkItDown is a Python utility for converting files to Markdown for use with LLMs and related text analysis pipelines. This repository is intended to provide Python libraries that can be incorporated into other systems — not the end-user applications built on top of them.

#### In scope

- Improvements to the fidelity of existing converters (New formats are added sparingly -- especially if they incur new dependencies. In most cases, new formats can be better supported via [3rd-party plugins](#extending-markitdown-without-changing-this-repository).)
- Bug fixes, performance improvements, and security fixes
- The `markitdown` command-line interface
- The `markitdown-mcp` package
- Tests, documentation, and developer tooling

#### Out of scope

We cannot accept additional applications, services, or servers. This includes:

- Web servers, REST or HTTP APIs, and hosted conversion services
- Web frontends and browser-based user interfaces
- Desktop and mobile applications (PyQt, PySide, Tkinter, Electron, Flutter, and similar)

Projects like these are genuinely useful, and we would rather see them thrive than be turned away. If you are interested in providing a web service, API, or graphical application for MarkItDown, please maintain it as a separate package or project that depends on [`markitdown` from PyPI](https://pypi.org/project/markitdown/).

### Extending MarkItDown Without Changing This Repository

MarkItDown supports 3rd-party plugins, so support for a new format can be published and installed independently of this repository:

```sh
markitdown --list-plugins
markitdown --use-plugins path-to-file.pdf
```

See `packages/markitdown-sample-plugin` to get started, and tag your repository `#markitdown-plugin` so that others can find it.

### How to Contribute

You can help by looking at issues or helping review PRs. We have also marked some issues as 'open for contribution' and PRs as 'open for reviewing' to help facilitate community contributions. These labels are suggestions; contributions within the scope described above are welcome.

<div align="center">

|            | All                                                          | Especially Needs Help from Community                                                                                                      |
| ---------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **Issues** | [All Issues](https://github.com/microsoft/markitdown/issues) | [Issues open for contribution](https://github.com/microsoft/markitdown/issues?q=is%3Aissue+is%3Aopen+label%3A%22open+for+contribution%22) |
| **PRs**    | [All PRs](https://github.com/microsoft/markitdown/pulls)     | [PRs open for reviewing](https://github.com/microsoft/markitdown/pulls?q=is%3Apr+is%3Aopen+label%3A%22open+for+reviewing%22)              |

</div>

### Running Tests and Checks

- Navigate to the MarkItDown package:

  ```sh
  cd packages/markitdown
  ```

- Install `hatch` in your environment and run tests:

  ```sh
  pip install hatch  # Other ways of installing hatch: https://hatch.pypa.io/dev/install/
  hatch shell
  hatch test
  ```

  (Alternative) Use the Devcontainer which has all the dependencies installed:

  ```sh
  # Reopen the project in Devcontainer and run:
  hatch test
  ```

- Run pre-commit checks before submitting a PR: `pre-commit run --all-files`

### Security Considerations

MarkItDown performs I/O with the privileges of the current process. Like `open()` or `requests.get()`, it will access resources that the process itself can access.

**Sanitize your inputs:** Do not pass untrusted input directly to MarkItDown. If any part of the input may be controlled by an untrusted user or system, such as in hosted or server-side applications, it must be validated and restricted before calling MarkItDown. Depending on your environment, this may include restricting file paths, limiting URI schemes and network destinations, and blocking access to private, loopback, link-local, or metadata-service addresses.

**Call only the conversion method you need:** Prefer the narrowest conversion API that fits your use case. MarkItDown's `convert()` method is intentionally permissive and can handle local files, remote URIs, and byte streams. If your application only needs to read local files, call `convert_local()` instead. If you need more control over URI fetching, call `requests.get()` yourself and pass the response object to `convert_response()`. For maximum control, open a stream to the input you want converted and call `convert_stream()`.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
