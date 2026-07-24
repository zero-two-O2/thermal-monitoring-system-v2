"""
Application entry point.
"""
import sys
from app.application import Application

def main() -> None:
    application = Application()
    sys.exit(application.run())

if __name__ == "__main__":
    main()