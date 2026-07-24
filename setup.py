"""
py2app build script. Produces a real .app bundle (proper name, icon, and
process identity in Activity Monitor/notifications/alerts — a plain
`python3 menubar_app.py` process otherwise inherits Python's own generic
bundle identity). Run via install.sh, or directly:

    python3 setup.py py2app
"""

from setuptools import setup

APP_NAME = "MN-routes"
BUNDLE_ID = "com.mnroutes.app"

setup(
    app=["menubar_app.py"],
    data_files=[],
    options={
        "py2app": {
            "iconfile": "AppIcon.icns",
            "packages": ["rumps"],
            "plist": {
                "CFBundleName": APP_NAME,
                "CFBundleDisplayName": APP_NAME,
                "CFBundleIdentifier": BUNDLE_ID,
                "CFBundleShortVersionString": "1.0.0",
                "LSUIElement": True,  # menu bar only, no Dock icon
            },
        },
    },
    setup_requires=["py2app"],
)
