import os

# GUI tests run headless (CI has no display); keep test runs away from the real settings.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
