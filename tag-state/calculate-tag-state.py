#!/usr/bin/env python
import argparse
from collections.abc import Iterable
import json
import operator
import os
from pathlib import Path
import re
import signal
import sys
import subprocess

# requires docker be available on the CLI

# constants
SPLIT_VERSION_REGEX = re.compile("[.+-]")
NEEDS_MANIFEST = "NEEDS_MANIFEST"
PENDING = "PENDING"
SUCCESS = "SUCCESS"
FAILED = "FAILED"


# distutils.version.LooseVersion is deprecated. packaging.version is the recommended replacement but I'd like to
# keep this script vanilla. This is an attempt at re-implementation good enough for our purposes.
class LooseVersion:
    def __init__(self, s):
        self.vs = SPLIT_VERSION_REGEX.split(s)
        self.n = max(len(x) for x in self.vs)

    def cmp(self, other, op):
        n = max(self.n, other.n)
        return op(
            tuple(x.zfill(n) for x in self.vs), tuple(x.zfill(n) for x in other.vs)
        )

    def __lt__(self, other):
        return self.cmp(other, operator.lt)

    def __le__(self, other):
        return self.cmp(other, operator.le)

    def __gt__(self, other):
        return self.cmp(other, operator.gt)

    def __ge__(self, other):
        return self.cmp(other, operator.ge)

    def __eq__(self, other):
        return self.cmp(other, operator.eq)

    def __ne__(self, other):
        return self.cmp(other, operator.ne)


def signal_handler(sig, frame):
    print_error("Exiting due to Ctrl+C")
    sys.exit(0)


def print_error(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def pad_none(iterable: Iterable, length: int, padding=None) -> Iterable:
    return iterable + [None] * (length - len(iterable))


def create_script_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="""Script that reconstructs tag state from buildlog records. Depends on buildlog staying ordered by
                       date. A JSON object with all recognized tags to image hashes/digests will be printed to stdout.
                       Any issues during the process will be printed to stderr."""
    )
    parser.add_argument(
        "buildlog_file_path",
        type=Path,
        help="Path to the buildlog you want to calculate tag state for.",
    )
    return parser


def read_buildlog_file(buildlog_file_path: Path) -> dict:
    if os.path.exists(buildlog_file_path):
        with open(buildlog_file_path) as buildlog:
            buildlog_data = json.loads(buildlog.read())
            buildlog.close()
            return buildlog_data
    else:
        print_error(f"Buildlog not found at {parsed_args.buildlog_file_path}")


def semver_sorted_dict(d: dict) -> dict:
    return dict(sorted(d.items(), key=lambda i: LooseVersion(i[0])))


def build_tag_state(buildlog_data: list) -> dict:
    tag_state = {}
    for buildlog_entry in buildlog_data:
        if "container_hash" in buildlog_entry and "version" in buildlog_entry:
            version = buildlog_entry["version"]
            digest = buildlog_entry["container_hash"]
            major, minor, patch, arch = pad_none(
                version.replace(".", "-").split("-"), 4
            )
            manifest_semver = f"{major}.{minor}.{patch}"
            medium_tag = f"{major}.{minor}"
            if arch:
                tag_state[version] = {"digest": digest, "status": PENDING}
                tag_state[major] = {"digest": NEEDS_MANIFEST, "status": PENDING}
                tag_state[medium_tag] = {
                    "digest": NEEDS_MANIFEST,
                    "status": PENDING,
                }
                tag_state[manifest_semver] = {
                    "digest": NEEDS_MANIFEST,
                    "status": PENDING,
                }
            else:
                if manifest_semver in tag_state:
                    # if the current digest for our major or minor tag is the previous version of this container, update it
                    if (
                        tag_state[major]["digest"]
                        is tag_state[manifest_semver]["digest"]
                    ):
                        tag_state[major]["digest"] = digest
                    if (
                        tag_state[medium_tag]["digest"]
                        is tag_state[manifest_semver]["digest"]
                    ):
                        tag_state[medium_tag]["digest"] = digest
                    # update the full tag to the new version of the container always
                    tag_state[manifest_semver] = {"digest": digest, "status": PENDING}
                else:
                    tag_state[major] = {"digest": digest, "status": PENDING}
                    tag_state[f"{major}.{minor}"] = {
                        "digest": digest,
                        "status": PENDING,
                    }
                    tag_state[manifest_semver] = {"digest": digest, "status": PENDING}
        else:
            print_error(
                f"Buildlog entry found without associated container hash: {buildlog_entry}"
            )
    return semver_sorted_dict(tag_state)


def pretty_printable_dict(d: dict) -> str:
    return json.dumps(
        d,
        indent=4,
        sort_keys=False,
    )


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    arg_parser = create_script_arg_parser()
    parsed_args = arg_parser.parse_args(sys.argv[1:])
    buildlog_data = read_buildlog_file(parsed_args.buildlog_file_path)
    tag_state = build_tag_state(buildlog_data)
    print(pretty_printable_dict(tag_state))
    # tag and push everything that doesn't need a manifest
    image_name = parsed_args.buildlog_file_path.stem
    for key, value in tag_state.items():
        if value["digest"] is not NEEDS_MANIFEST:
            # Errors will show up here where containers/versions have been removed either because of our retention
            # policy or ones that were yanked.
            image_name_by_digest = (
                f"gcr.io/ironcore-images/{image_name}@sha256:{value['digest']}"
            )
            pull = subprocess.run(["docker", "image", "pull", image_name_by_digest])
            # tag with the new value
            if pull.returncode is 0:
                tag = subprocess.run(
                    [
                        "docker",
                        "image",
                        "tag",
                        image_name_by_digest,
                        f"gcr.io/ironcore-images/{image_name}:{key}",
                    ]
                )
                if tag.returncode is 0:
                    push = subprocess.run(
                        ["docker", "push", f"gcr.io/ironcore-images/{image_name}:{key}"]
                    )
                    if push.returncode is 0:
                        value["status"] = SUCCESS
                        continue
            value["status"] = FAILED
    # print what was tagged
    successfully_tagged = {
        k: v["digest"] for k, v in tag_state.items() if v["status"] is SUCCESS
    }
    failed_tags = {
        k: v["digest"] for k, v in tag_state.items() if v["status"] is FAILED
    }
    needs_manifest = {
        k: v["digest"] for k, v in tag_state.items() if v["digest"] is NEEDS_MANIFEST
    }
    print(pretty_printable_dict(successfully_tagged))
    print_error(pretty_printable_dict(failed_tags))
    print(pretty_printable_dict(needs_manifest))
    # use the tags just pushed to create manifests
    link_manifest = {}
    for key in needs_manifest:
        # we expect no arch tags at this point
        major, minor, patch = pad_none(key.split("."), 3)
        # if there's a patch we need to create a manifest for it
        if patch:
            gcr_image = f"gcr.io/ironcore-images/{image_name}:{key}"
            # all our images that need manifests have arm64/amd64 versions
            create_manifest = subprocess.run(
                [
                    "docker",
                    "manifest",
                    "create",
                    gcr_image,
                    f"{gcr_image}-arm64",
                    f"{gcr_image}-amd64",
                ]
            )
            if create_manifest.returncode is 0:
                annotate_manifest_arm = subprocess.run(
                    [
                        "docker",
                        "manifest",
                        "annotate",
                        gcr_image,
                        f"{gcr_image}-arm64",
                        "--arch",
                        "arm64",
                    ]
                )
                annotate_manifest_amd = subprocess.run(
                    [
                        "docker",
                        "manifest",
                        "annotate",
                        gcr_image,
                        f"{gcr_image}-amd64",
                        "--arch",
                        "amd64",
                    ]
                )
                # if creation and annotation worked, push the new manifest
                if (
                    annotate_manifest_arm.returncode is 0
                    and annotate_manifest_amd.returncode is 0
                ):
                    # rebuilds aren't a factor now and the tags are semver sorted, so the last writer is the right one
                    major_manifest_name = f"gcr.io/ironcore-images/{image_name}:{major}"
                    minor_manifest_name = (
                        f"gcr.io/ironcore-images/{image_name}:{major}.{minor}"
                    )
                    subprocess.run(
                        [
                            "docker",
                            "manifest",
                            "create",
                            major_manifest_name,
                            f"{gcr_image}-arm64",
                            f"{gcr_image}-amd64",
                        ]
                    )
                    subprocess.run(
                        [
                            "docker",
                            "manifest",
                            "create",
                            minor_manifest_name,
                            f"{gcr_image}-arm64",
                            f"{gcr_image}-amd64",
                        ]
                    )
                    subprocess.run(["docker", "manifest", "push", gcr_image])
                    subprocess.run(["docker", "manifest", "push", major_manifest_name])
                    subprocess.run(["docker", "manifest", "push", minor_manifest_name])
