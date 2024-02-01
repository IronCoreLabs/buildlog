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

split_version_re = re.compile("[.+-]")


# distutils.version.LooseVersion is deprecated. packaging.version is the recommended replacement but I'd like to
# keep this script vanilla. This is an attempt at re-implementation good enough for our purposes.
class LooseVersion:
    def __init__(self, s):
        self.vs = split_version_re.split(s)
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


def build_tag_state(buildlog_data: list) -> dict:
    tag_state = {}
    for buildlog_entry in buildlog_data:
        if "container_hash" in buildlog_entry and "version" in buildlog_entry:
            version = buildlog_entry["version"]
            digest = buildlog_entry["container_hash"]
            major, minor, patch, arch = pad_none(
                version.replace(".", "-").split("-"), 4
            )
            if arch:
                tag_state[version] = digest
                # TODO: need to create a manifest that gets all the else tags of both digests
            else:
                if f"{major}.{minor}.{patch}" in tag_state:
                    tag_state[f"{major}.{minor}.{patch}"] = digest
                else:
                    tag_state[major] = digest
                    tag_state[f"{major}.{minor}"] = digest
                    tag_state[f"{major}.{minor}.{patch}"] = digest
        else:
            print_error(
                f"Buildlog entry found without associated container hash: {buildlog_entry}"
            )
    return tag_state


def semver_sorted_dict(d: dict) -> str:
    return json.dumps(
        dict(sorted(tag_state.items(), key=lambda i: LooseVersion(i[0]))),
        indent=4,
        sort_keys=False,
    )


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    arg_parser = create_script_arg_parser()
    parsed_args = arg_parser.parse_args(sys.argv[1:])
    buildlog_data = read_buildlog_file(parsed_args.buildlog_file_path)
    tag_state = build_tag_state(buildlog_data)
    print(semver_sorted_dict(tag_state))
