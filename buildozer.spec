[app]

# Όνομα που φαίνεται στο tablet
title = Ναυμαχία
package.name = naumaxia
package.domain = io.github.alextsapi

source.dir = .
source.include_exts = py,png,ttf,txt
source.exclude_dirs = .github, bin, out, __pycache__, recipes

version = 1.0
# Python 3.11 + pygame 2.6.1 (δικό μας recipe στον φάκελο recipes/)
requirements = python3==3.11.14,hostpython3==3.11.14,pygame

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #08142A

orientation = landscape
fullscreen = 1

# Χρειάζεται δίκτυο για να παίζουν 2 συσκευές μαζί (ίδιο Wi-Fi)
android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE

android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = True

p4a.bootstrap = sdl2
# σταθερή έκδοση του python-for-android, για να μη σπάει από αλλαγές
p4a.branch = v2026.05.09
p4a.local_recipes = ./recipes

[buildozer]
log_level = 2
warn_on_root = 0
