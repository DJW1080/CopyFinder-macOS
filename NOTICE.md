# Source and artwork provenance

CopyFinder for macOS uses the independently written Python/GTK application created
for [CopyFinder-LinuxMint](https://github.com/DJW1080/CopyFinder-LinuxMint) as its
shared behavioral foundation. The macOS desktop services, portability changes,
application-bundle packaging, native acceptance checks, and Mac documentation were
written for this repository. Linux GIO/XDG behavior remains isolated from native
Finder, Foundation Trash, volume, settings, and log integration.

The original Windows project was used as a behavioral and visual specification only:
[CopyFinder Windows](https://github.com/DJW1080/CopyFinder/tree/d90fa7b502326bfcac2df55fa1c87de2ed0e1543),
version 2.1.8. No Windows application source was ported.

Files under `copyfinder/assets` originate from that reference commit's Technification
artwork: the banner, application icon, and file-category icons. The reference
repository identifies its work as CC0 1.0. The included LICENSE is its published
dedication text.

CopyFinder was created and directed by Dean John Weiniger, who maintains the project.
OpenAI Codex is credited as the AI development co-contributor for the independently
written Linux foundation and native macOS integration, tests, packaging, and
documentation. This work was produced at Dean's request and under his direction.
