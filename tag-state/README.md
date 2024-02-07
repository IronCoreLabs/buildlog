# Buildlog Tag State

This script is used to repair IronCore's Google Container Registry in case tags ever get out of sync with the buildlog. GCR is deprecated but this same script could be modified to move from GCR to GAR (or to clone IronCore's public images with tags into a local repository based on the public buildlog).

## Usage

Requires the `docker` CLI tool to be installed and working. If pushing to IronCore's GCR, you must be correctly authenticated (use `icl-auth`).

```console
./fix-tag-state.py ../tenant-security-proxy.json
```

The script will use the buildlog to print out the correct state of images and their tags. It'll then pull the image digests referenced by that state and push that state out into GCR.

> WARNING: there's currently no dry run functionality, if you run it and don't kill it when it first starts running docker commands, things will be changed.
