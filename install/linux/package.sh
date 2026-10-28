#!/bin/bash
# Builds dist/mouthpiece-<version>-linux.tar.gz: the app plus install.sh / uninstall.sh at the top.
#   install/linux/package.sh 1.0.0
set -euo pipefail
cd "$(dirname "$0")/../.."
version=${1:?version}
name=mouthpiece-$version-linux
stage=$(mktemp -d)/$name
mkdir -p "$stage" dist
cp server.py server_model.py fetch_model.py audio.py cli.py launcher.pyw start.sh setup.sh requirements.txt pronuncia.json README.md "$stage"/
cp -r static claude-skill "$stage"/
mkdir -p "$stage/brand/icon" "$stage/voices"
cp brand/icon/icon.svg brand/icon/icon-256.png "$stage/brand/icon/"
cp voices/README.md "$stage/voices/"
cp install/linux/install.sh install/linux/uninstall.sh "$stage"/
tar -C "$(dirname "$stage")" -czf "dist/$name.tar.gz" "$name"
ls -lh "dist/$name.tar.gz"
