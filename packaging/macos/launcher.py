"""Frozen application entry point, including explicit isolated acceptance mode."""
import sys
from pathlib import Path

if len(sys.argv) == 3 and sys.argv[1] == '--macos-acceptance':
    from scripts.macos_acceptance import run_native_acceptance
    run_native_acceptance(Path(sys.argv[2]))
else:
    from copyfinder.app import main
    raise SystemExit(main())
