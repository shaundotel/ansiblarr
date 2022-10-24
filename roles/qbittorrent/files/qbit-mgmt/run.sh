#!/bin/sh
python3 -m ensurepip --upgrade
pip3 install pyyaml jsonschema qbittorrent-api

/config/qbit-mgmt/qbit-mgmt.py apply
#/config/qbit-mgmt/qbit-mgmt.py untracked-files --cleanup