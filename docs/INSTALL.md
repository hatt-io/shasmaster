# Install Shas Master

Choose the instructions for your computer below.

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

Linux users [build from source](https://github.com/hatt-io/shasmaster/blob/main/docs/BUILD-LINUX.md). No Linux installer is supplied.

## Meanings, backups and updates

Click a Hebrew word and type your meaning. Saved meanings are offered again for exactly the same Hebrew spelling. Use the reader's backup and restore controls to keep an extra copy of your work.

Close Shas Master before installing an update. Install the new version over the existing application. Your meanings and other saved work are stored separately from the application:

- Windows: `%LOCALAPPDATA%\Shas Master`
- Mac: `~/Library/Application Support/Shas Master`
- Linux: `$XDG_DATA_HOME/shas-master`, or `~/.local/share/shas-master` when that variable is unset.

Keep these personal-data folders when replacing the application. Do not put personal work into the application installation folder.
