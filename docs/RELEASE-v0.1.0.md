# Shas Master 0.1.0

Offline Shas reader with personal word meanings. All 5,405 prepared pages and their fonts are included.

## Downloads

| Mac | Windows | Linux |
| :---: | :---: | :---: |
| **[Download for Mac](https://github.com/hatt-io/shasmaster/releases/download/v0.1.0/Shas-Master-Native-macOS-arm64.dmg)** | **[Download for Windows](https://github.com/hatt-io/shasmaster/releases/download/v0.1.0/Shas-Master-Native-Windows-x64-unsigned.exe)** | **[Download for Linux](https://github.com/hatt-io/shasmaster/releases/download/v0.1.0/Shas-Master-x86_64.AppImage)** |
| Apple Silicon · 287 MB | x64 · 264 MB | Intel/AMD x64 · 286 MB |
| macOS 13+ | Windows 10 version 2004+ | AppImage · glibc 2.35+ |

Open the Mac download and drag the app to Applications. On Windows, run the installer. On Linux, allow the AppImage to run as a program in its file properties, then double-click it. No distribution-specific package manager is needed.

Mac is signed and Apple notarized. Windows is unsigned and may show an unknown-publisher warning. Windows and Linux have separate project signatures; these do not confer operating-system publisher approval. This release does not include Intel Mac or ARM Linux builds.

The Linux reader passed runtime, save/restart and backup checks on Ubuntu 22.04 and Fedora 43. It requires an Intel/AMD 64-bit computer, glibc 2.35 or later, a desktop session and a browser. Normal AppImage launch uses the system's FUSE device; the FUSE library is bundled. Systems without FUSE can use AppImage's extract-and-run option. This is not a claim of support for every Linux distribution; musl-based systems such as Alpine are excluded. Graphical double-click behavior has not been separately verified.

## Your saved work

Close the app before updating. Personal meanings, bookmarks and backups live outside the application and are retained when replacing it. Use Settings → Export to keep an additional copy of your work.

## Credits and terms

Source edition courtesy of **Shas.org, HebrewBooks.org and Moznaim / הוצאת ח. וגשל**. Source material is supplied free for personal, non-commercial educational use under its own terms. The app's MIT code license does not relicense those materials or fonts.

Download **Shas-Master-Notices.zip** alongside the installer for the full source terms, software notices, credits and installation guide. See [credits](https://github.com/hatt-io/shasmaster/blob/main/CREDITS.md) and [installation instructions](https://github.com/hatt-io/shasmaster/blob/main/docs/INSTALL.md).

`SHA256SUMS.txt` records the checksums of the installers and notices archive. The `.asc` files and `Shas-Master-signing-public.asc` provide the existing project signatures for Windows and Linux.
