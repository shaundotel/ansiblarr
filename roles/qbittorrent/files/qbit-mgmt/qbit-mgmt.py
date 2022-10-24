#!/usr/bin/env python3
# Use this code snippet in your app.
# If you need more information about configurations or implementing the sample code, visit the AWS docs:
# https://aws.amazon.com/developers/getting-started/python/

import argparse
import glob
import os
import pprint
import re
from pathlib import Path
from urllib.parse import urlparse

import qbittorrentapi
import yaml
import random
import string
from datetime import datetime
from jsonschema import validate


class Cli(object):
    main_parser = argparse.ArgumentParser(description="QB Management Utility")
    subparsers = main_parser.add_subparsers(dest="subcommand")

    def Subcommand(args=[], parent=subparsers):
        def decorator(func):
            parser = parent.add_parser(
                func.__name__.replace("_", "-"), description=func.__doc__
            )
            for arg in args:
                parser.add_argument(*arg[0], **arg[1])
            parser.set_defaults(func=func)

        return decorator

    def Argument(*name_or_flags, **kwargs):
        """Convenience function to properly format arguments to pass to the
        subcommand decorator.
        """
        return (list(name_or_flags), kwargs)

    def __call__(self):
        args = self.main_parser.parse_args()
        qbit_config = QbitMgmtConfig()

        self.qbit_mgmt = QbitMgmt(config=qbit_config)

        if args.subcommand is None:
            self.main_parser.print_help()
        else:
            args.func(self, args)

    @Subcommand()
    def apply(self, args):
        """
        Apply the configuration to the Qbit instance and the torrents it has.
        """
        self.qbit_mgmt.apply_tracker_tags()
        self.qbit_mgmt.apply_seed_limits()
        self.qbit_mgmt.apply_categories_path()

    @Subcommand(
        [
            Argument(
                "--cleanup", action="store_true", help="Move untracked files to trash"
            )
        ]
    )
    def untracked_files(self, args):
        """
        Get a data on untracked files
        """
        self.qbit_mgmt.untracked_files(cleanup=args.cleanup)


class QbitMgmtConfig(object):
    def __init__(self):

        config_file_path = os.path.join(os.path.dirname(__file__), "config.yml")
        config_schema_path = os.path.join(
            os.path.dirname(__file__), "config-schema.yml"
        )

        with open(config_file_path, "r") as fp:
            config_data = yaml.safe_load(fp)

        with open(config_schema_path, "r") as fp:
            config_schema = yaml.safe_load(fp)

        validate(instance=config_data, schema=config_schema)

        for key, value in config_data.items():
            key = key.replace("-", "_")
            setattr(self, key, value)


class QbitMgmt(object):
    def __init__(self, config: QbitMgmtConfig) -> None:
        self.qbt_client = qbittorrentapi.Client(**config.qbit)
        self.config = config
        self.torrent_list = None
        self.tag_spec = None
        self.torrent_files = None
        self.torrent_categories = None

    def get_torrents(self, *args, **kwargs):
        if self.torrent_list is None:
            self.torrent_list = self.qbt_client.torrents.info(*args, **kwargs)

            # Process the torrent data to assist later on with the process
            for torrent in self.torrent_list:
                # Convert the tags into a list
                torrent["tags"] = [x.strip() for x in torrent.tags.split(",")]

        return self.torrent_list

    def get_torrent_categories(self, recheck=False):
        if self.torrent_categories is None or recheck:
            self.torrent_categories = self.qbt_client.torrents_categories()

        return self.torrent_categories

    def get_torrent_files(self, recheck=False) -> dict:
        if self.torrent_files is None or recheck:

            torrent_files = dict()

            for torrent in self.get_torrents():
                torrent_files.setdefault(torrent.hash, [])
                for _file in torrent.files:
                    torrent_files[torrent.hash].append(
                        os.path.join(torrent.save_path, _file.name)
                    )
            self.torrent_files = torrent_files

        return self.torrent_files

    def untracked_files(self, cleanup=False):

        all_tracked_files = [
            path for hash, files in self.get_torrent_files().items() for path in files
        ]
        all_category_paths = [
            category_data["savePath"]
            for category_data in self.get_torrent_categories().values()
        ]
        cleanup_required = False
        untracked_files = []
        empty_dirs = []
        for _file in Path(self.config.root_dir).rglob("*"):
            if Path(self.config.recycle_bin) in _file.parents:
                continue
            elif (
                _file.is_dir()
                and len(os.listdir(_file)) == 0
                and str(_file.resolve()) not in all_category_paths
            ):
                empty_dirs.append(_file.resolve())
                cleanup_required = True
            elif _file.is_file() and str(_file.resolve()) not in all_tracked_files:
                untracked_files.append(_file.resolve())
                cleanup_required = True

        print("Empty Dirs:")
        pprint.pprint(empty_dirs)
        print("*" * 10)
        print("Untracked Files:")
        pprint.pprint(untracked_files)
        print("*" * 10)
        print(f"Total tracked files: {len(all_tracked_files)}")
        print(f"Total untracked files: {len(untracked_files)}")
        print(f"Total empty dirs: {len(empty_dirs)}")

        if cleanup and cleanup_required:
            untoucable_dirs = [Path(x) for x in all_category_paths]
            untoucable_dirs.extend(
                [Path(self.config.root_dir), Path(self.config.recycle_bin)]
            )
            recycle_instance_dir = self.config.recycle_bin.joinpath(
                datetime.now().strftime("%Y%m%d"),
                "".join(random.choice(string.ascii_letters) for i in range(10)),
            )
            if recycle_instance_dir.exists():
                raise Exception(
                    f"Recycle Dir already exists. Rerun for a new random dir: {recycle_instance_dir}"
                )
            else:
                recycle_instance_dir.mkdir(parents=True)

            for _file in untracked_files:
                new_path = Path(recycle_instance_dir).joinpath(*_file.parts[2:])
                new_path.parent.mkdir(parents=True, exist_ok=True)
                new_path.hardlink_to(_file)
                _file.unlink()

            for _dir in empty_dirs:
                _dir.rmdir()
                for parent in _dir.parents:
                    if parent in untoucable_dirs:
                        break
                    parent.rmdir()

        return untracked_files, empty_dirs

    def create_tag_spec(self) -> dict:
        """
        Create a tag specification dictionary which can be used to apply tags to
        torrents.
        The dictionary returns data in the following manner:
        add:
            <tag>: [list of hashes]
        remove:
            <tag>: [list of hashes]
        """
        if self.tag_spec is None:
            torrent_list = self.get_torrents()
            add_tag_spec = dict()
            remove_tag_spec = dict()

            for torrent in torrent_list:
                add_tags = set()
                remove_tags = set()
                _add_tracker_tags, _remove_tracker_tags = self._create_tracker_tag_spec(
                    torrent
                )
                add_tags.update(_add_tracker_tags)
                remove_tags.update(_remove_tracker_tags)

                (
                    _add_tracker_tags,
                    _remove_tracker_tags,
                ) = self._create_file_extention_tag_spec(torrent)
                add_tags.update(_add_tracker_tags)
                remove_tags.update(_remove_tracker_tags)

                for tag in add_tags:
                    add_tag_spec.setdefault(tag, [])
                    add_tag_spec[tag].append(torrent.hash)
                for tag in remove_tags:
                    remove_tag_spec.setdefault(tag, [])
                    remove_tag_spec[tag].append(torrent.hash)

            self.tag_spec = {}
            self.tag_spec["remove"] = remove_tag_spec
            self.tag_spec["add"] = add_tag_spec

        return self.tag_spec

    def _create_tracker_tag_spec(self, torrent):
        tagged = False
        tracker_tags = set()
        tracker_tag_prefix = self.config.tag_prefix["tracker"]
        add_tracker_tags = set()
        remove_tracker_tags = set()

        # Determine which tracker tag rule should apply
        for regex_rule in self.config.tracker_tags:
            url_host_regex = regex_rule["url_host_regex"]
            tag = f"{tracker_tag_prefix}{regex_rule['tag']}"

            if isinstance(url_host_regex, list):
                pass
            elif isinstance(url_host_regex, str):
                url_host_regex = [url_host_regex]

            for tracker in torrent.trackers:
                tracker_url = urlparse(tracker.url)

                for regex in url_host_regex:
                    if re.match(regex, tracker_url.netloc):
                        tracker_tags.add(tag)
                        break

                if len(tracker_tags) > 0:
                    break

            if len(tracker_tags) > 0:
                break

        # Create a set with current tracker tags
        current_tracker_tags = {
            current_tags
            for current_tags in torrent.tags
            if re.search(f"^{re.escape(tracker_tag_prefix)}.*$", current_tags)
        }

        remove_tracker_tags = current_tracker_tags.difference(tracker_tags)
        add_tracker_tags = tracker_tags.difference(current_tracker_tags)

        return add_tracker_tags, remove_tracker_tags

    def _create_file_extention_tag_spec(self, torrent):
        tagged = False
        file_extension_tags = set()
        file_extension_tag_prefix = self.config.tag_prefix["file"]
        add_file_extension_tags = set()
        remove_file_extension_tags = set()

        # Determine which file extension tag rule should apply
        for regex_rule in self.config.file_extension_tags:
            extension_regex = regex_rule["extension_regex"]
            tag = f"{file_extension_tag_prefix}{regex_rule['tag']}"

            if isinstance(extension_regex, list):
                pass
            elif isinstance(extension_regex, str):
                extension_regex = [extension_regex]

            torrent_files = self.get_torrent_files().get(torrent.hash, [])

            for _file in torrent_files:

                for regex in extension_regex:
                    if re.match(regex, _file):
                        file_extension_tags.add(tag)

        # Create a set with current file extension tags
        current_file_extension_tags = {
            current_tags
            for current_tags in torrent.tags
            if re.search(f"^{re.escape(file_extension_tag_prefix)}.*$", current_tags)
        }

        remove_file_extension_tags = current_file_extension_tags.difference(
            file_extension_tags
        )
        add_file_extension_tags = file_extension_tags.difference(
            current_file_extension_tags
        )

        return add_file_extension_tags, remove_file_extension_tags

    def apply_tracker_tags(self):
        tag_spec = self.create_tag_spec()
        hash_spec = {hash: tag for tag, hashes in tag_spec.items() for hash in hashes}

        for add_tag, hashes in tag_spec["add"].items():
            self.qbt_client.torrents_add_tags(add_tag, hashes)

        for remove_tag, hashes in tag_spec["remove"].items():
            for torrent_hash in hashes:
                self.qbt_client.torrents_remove_tags(remove_tag, torrent_hash)

    def apply_seed_limits(self):
        for torrent in self.get_torrents():
            torrent_tag = torrent.tags
            set_seeding_time_limit = torrent.seeding_time_limit
            set_ratio_limit = torrent.ratio_limit

            required_seeding_time_limit = -2
            required_ratio_limit = -2

            for tag in torrent_tag:
                rules = self.config.seed_limits.get(tag, None)
                if rules is not None:
                    required_seeding_time_limit = rules.get("ratio", -2)
                    required_ratio_limit = rules.get("ratio", -2)
                    break

            if (
                required_seeding_time_limit != set_seeding_time_limit
                or required_ratio_limit != set_ratio_limit
            ):
                self.qbt_client.torrents_set_share_limits(
                    ratio_limit=required_ratio_limit,
                    seeding_time_limit=required_seeding_time_limit,
                    torrent_hashes=torrent.hash,
                )

    def apply_categories_path(self):
        for category in self.get_torrent_categories().values():
            save_path = os.path.join(self.config.root_dir, category.name)
            if category.savePath != save_path:
                self.qbt_client.torrents_edit_category(
                    name=category.name,
                    save_path=save_path,
                    download_path=save_path,
                    enable_download_path=True,
                )
        self.get_torrent_categories(recheck=True)


if __name__ == "__main__":
    cli = Cli()()
