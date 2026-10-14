# Credits and licensing

Shas Master is maintained by [hatt-io](https://github.com/hatt-io).

## Printed source material

The source edition is provided courtesy of:

- [Shas.org](https://www.shas.org/dafviewer), providing access to the daf collection.
- [HebrewBooks.org](https://www.hebrewbooks.org/shas), preserving and making the source publications available.
- **Moznaim / הוצאת ח. וגשל**, the credited publisher of the source edition.

The installed app contains prepared text, layout information and the original font data derived from this edition. These materials remain subject to their original rights and notices. They are **not covered by the app's MIT license**.

The [source provider's redistribution instructions](https://www.shas.org/daf-pdf/api/api-documentation.html) require free, non-commercial distribution, attribution and inclusion of the HebrewBooks limited license. Copies of the [HebrewBooks terms](docs/licenses/HebrewBooks-terms.html), [Shas.org instructions](docs/licenses/Shas-source-terms.html) and [attribution](docs/licenses/ATTRIBUTION.txt) are retained here and accompany the release. The HebrewBooks document contains the complete Paragraph 1 limited license and its restrictions on further distribution.

## Application code

Original Shas Master application code is available under the [MIT License](LICENSE). This permission does not relicense source publications, their fonts, third-party libraries, or third-party trademarks. In particular, permission to sell copies of the application code does not grant permission to sell the bundled source material.

## Software acknowledgments

Shas Master uses work from these projects and their contributors:

| Project | Role |
| :--- | :--- |
| [React](https://react.dev/) | Reading interface |
| [TypeScript](https://www.typescriptlang.org/) and [Vite](https://vite.dev/) | Interface development and production builds |
| [Python](https://www.python.org/) | Local application service |
| [FastAPI](https://fastapi.tiangolo.com/), [Starlette](https://www.starlette.io/) and [Uvicorn](https://www.uvicorn.org/) | Local requests and page delivery |
| [Pydantic](https://docs.pydantic.dev/) | Data validation |
| [SQLite](https://sqlite.org/) | Saved work, catalogue and search |
| [fontTools](https://fonttools.readthedocs.io/) | Font processing |
| [PyInstaller](https://pyinstaller.org/) | Bundled local runtime |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | Windows installer |
| [AppImage](https://appimage.org/) | Portable Linux package and bundled launch runtime |
| [WebKit](https://webkit.org/) and Apple AppKit | Mac application window |
| [.NET Framework](https://dotnet.microsoft.com/en-us/download/dotnet-framework) | Windows launcher |
| [PyMuPDF](https://pymupdf.readthedocs.io/), [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) and [HTTPX](https://www.python-httpx.org/) | Developer-side source preparation; excluded from the installed reader |

Third-party software retains its own licenses. Collected license texts are in [docs/licenses/software](docs/licenses/software). These acknowledgments do not imply endorsement by the credited projects or source providers.
