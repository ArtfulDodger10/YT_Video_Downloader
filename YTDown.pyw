# Double-click launcher (no console window). No arguments opens the GUI; with arguments it
# downloads headlessly like `python -m ytdown ...` (exit code 0 = all succeeded).
from ytdown.cli import main

raise SystemExit(main())
