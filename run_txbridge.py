"""Entry point for running from source and for PyInstaller builds."""
from txbridge.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
