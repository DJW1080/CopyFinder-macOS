# CopyFinder for MacOS 10.15.8 Catalina 

![CopyFinder](Technification/Logo/CopyFinder-Banner-08.png)

![Intel](https://img.shields.io/badge/CPU-Intel-31c5f3?logo=intel "Intel Compatible")
![AMD](https://img.shields.io/badge/CPU-AMD-00a774?logo=amd "AMD Compatible")
![Made in Melbourne](https://img.shields.io/badge/🌏%20Made%20in-Melbourne-FFB6C1?style=flat "Made in Melbourne")
![Licence](https://img.shields.io/badge/📜%20Licence-CC0%201.0-lightgrey.svg?style=flat "CC0 1.0 Universal")
![Version 0.1.0](https://img.shields.io/badge/Version-0.1.0-yellow?logo=version "Version 0.1.0")

**CopyFinder** is a native **MacOS** duplicate-file scanner written from scratch in Swift. It follows the established **CopyFinder** workflow while using Apple system frameworks for its interface, file access, SHA-256 comparison, Finder integration, and Trash.

## What it does

- Scans a chosen folder and its subfolders  
- Considers files duplicates only when size and SHA-256 content match  
- Offers Original, Shortest name, Oldest file, Newest file, Folder, and Highest Resolution keep rules  
- Review groups, change the kept file, reveal files in Finder, and select duplicates  
- Rechecks both files immediately before moving a selected duplicate to the macOS Trash  

## Build

On a Mac with **Xcode** command-line tools:

```sh
make build
```

The build creates a DMG, ZIP, checksums, build details, and the result of one smoke test under `dist/macos/`. The build has a 110-second limit.

## 📝 Credits

Created and directed by **Dean John Weiniger**.

The original interface styling concept was developed with assistance from **Copilot**.

**Human-AI collaboration — MacOS Mint edition**

CopyFinder was conceived and directed by Dean John Weiniger, who designed and refined the interface and product experience.  
Its application code was developed with assistance from ChatGPT by OpenAI and is presented as a demonstration of practical human-AI collaboration in desktop application development.

## 📜 Licence

This work is dedicated to the public domain under the **Creative Commons CC0 1.0 Universal License**.  
[![CC0 1.0](https://img.shields.io/badge/License-CC0%201.0-lightgrey?logo=creativecommons&logoColor=white)](https://creativecommons.org/publicdomain/zero/1.0/)  

**You are free to:**  
✅ **Share** – Copy and redistribute the material in any medium or format.  
✅ **Adapt** – Remix, transform, and build upon the material for any purpose, even commercially.  
✅ **Use without attribution** – No credit required, though it’s appreciated.

**No conditions apply:**  
🚫 No attribution required.  
🚫 No restrictions on use.  
**Full licence text:** [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/)  

---

### updated: 02-10-2026
