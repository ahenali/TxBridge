# Changelog

## 1.2.0

- GitHub Releases now build a Windows installer and portable zip, plus Linux AppImage and Debian/Ubuntu packages.
- Release checksums cover all platform installers.
- Documented the current FS-CT6A/B support boundary and the next radio families under consideration.

## 1.1.0

- New look: flat layout, neutral colours with a single blue accent, light and dark themes, and a "follow Windows" setting (now the default).
- New Setup page. It shows whether the USB cable, vJoy and ViGEmBus are present, and can download and start the vJoy and ViGEmBus installers. Downloads are limited to GitHub over HTTPS and are checked against a pinned SHA-256 (or, for newer releases, a valid Authenticode signature) before they run.
- Windows installer (Inno Setup) and a portable zip, built by GitHub Actions on version tags.
- App icon and taskbar identity.
- Scope legend: click a channel name to hide or show its trace.
- Layout fixes: nav buttons, truncated drop-downs, clipped sidebar footer, misaligned columns.
- A layout test renders every page at several window sizes and fails on clipped text or sideways scrolling.

## 1.0.0

First release: radio editor, live view, simulator output (vJoy, Xbox 360 pad, Linux uinput), model library, exports, backup and restore.
