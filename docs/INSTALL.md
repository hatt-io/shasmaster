# Install Shas Master

The downloads include all 5,405 pages and their fonts. Reading works offline. You do not need Python, Node, PDFs or development tools.

## Windows

For Windows 10 version 2004 or later, on x64-compatible computers.

1. Open `Shas-Master-Native-Windows-x64-unsigned.exe`.
2. Follow the installer and select **Open Shas Master** at the end.
3. Subsequently open **Shas Master** from the Start menu or desktop shortcut. It opens the reader in your default browser automatically.
4. To stop the app completely, choose **Quit** from its notification-area icon.

This installer does not have a Windows publisher certificate. Windows may show an unknown-publisher warning; managed computers may prohibit installation. The separate `.asc` file verifies the download using the project key but does not remove that warning.

## Mac

For Apple Silicon Macs running macOS 13 or later.

1. Open `Shas-Master-Native-macOS-arm64.dmg`.
2. Drag **Shas Master** to **Applications**.
3. Open **Shas Master** from Applications.

This download is Developer ID signed and Apple notarized.

## Linux

For ARM64 computers running a Debian-compatible desktop distribution.

1. Open `Shas-Master-Native-linux-arm64.deb` with your software installer and choose **Install**.
2. Open **Shas Master** from the applications menu. The reader opens in your default browser automatically.

The accompanying `.asc` signature uses the project key in `Shas-Master-signing-public.asc`. This package is not for ordinary Intel/AMD x64 Linux computers.

## Meanings, backups and updates

Click a Hebrew word and type your meaning. Saved meanings are offered again for exactly the same Hebrew spelling. Use the reader's backup and restore controls to keep an extra copy of your work.

Close Shas Master before installing an update. Install the new version over the existing application. Your meanings and other saved work are stored separately from the application:

- Windows: `%LOCALAPPDATA%\Shas Master`
- Mac: `~/Library/Application Support/Shas Master`
- Linux: `$XDG_DATA_HOME/shas-master`, or `~/.local/share/shas-master` when that variable is unset.

Keep these personal-data folders when replacing the application. Do not put personal work into the application installation folder.
