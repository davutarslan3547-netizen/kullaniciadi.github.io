[app]
title = Bakkal Kasa
package.name = bakkalkasa
package.domain = org.bakkal

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 1.0

# ssl için openssl + certifi şart (Firebase https)
requirements = python3,kivy==2.3.0,certifi,openssl

orientation = landscape
fullscreen = 0

android.permissions = INTERNET
android.api = 33
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
