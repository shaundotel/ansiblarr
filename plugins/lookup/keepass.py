# python 3 headers, required if submitting to Ansible
from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = """
  lookup: keepass
  author: Komail Kanjee <kkanjee@eeng.pro>
  version_added: "0.9"  # for collections, use the collection version, not the Ansible version
  short_description: KeePass lookup plugin for secrets
  description:
      - This lookup returns the data from KeePass
  options:
    _terms:
      description: path(s) of files to read
      required: True
    option1:
      description:
            - Sample option that could modify plugin behaviour.
            - This one can be set directly ``option1='x'`` or in ansible.cfg, but can also use vars or environment.
      type: string
      ini:
        - section: file_lookup
          key: option1
  notes:
    - if read in variable context, the file can be interpreted as YAML if the content is valid to the parser.
    - this lookup does not understand globing --- use the fileglob lookup instead.
"""


import os
from multiprocessing.sharedctypes import Value

import pykeepass
from ansible.errors import AnsibleError, AnsibleParserError
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display
import pykeepass.entry
from pykeepass.entry import Entry as KeepassEntry
from pykeepass.group import Group as KeepassGroup
import inspect

display = Display()


class LookupModule(LookupBase):
    def __init__(self, loader=None, templar=None, **kwargs):
        super().__init__(loader, templar, **kwargs)
        self.keepass = None

    def get_entry_attribute(self, path: str, attribute: str) -> str:
        """
        Get the attribute from a given path.

        Args:
          path(str): The full path of the entry including the entry name
          attribute(str): The name of the attribute to get
        """
        # Formulate the reserved keys that can't be used as attributes in custom
        # properties of an entry to avoid ambigious results
        reserved_keys = [
            _member[0]
            for _member in inspect.getmembers(
                KeepassEntry,
                lambda a: (inspect.isdatadescriptor(a)),
            )
        ]

        # reserved_keys = [x.lower() for x in pykeepass.entry.reserved_keys] + ['attachment']
        display.vvv(f"keepass: Reserved attribute keys: {reserved_keys}")

        entry = self.find_entry(path)

        entry_custom_properties = entry.custom_properties.keys()
        invalid_keys = set(reserved_keys).intersection(entry_custom_properties)

        if len(invalid_keys) > 0:
            raise AnsibleError(
                f"Found invalid key(s) {invalid_keys} in entry's custom properties of '{path}'"
            )

        # Gett the attribute, first from static keys and if not found from the cutom
        # properties
        attribute_val = None
        if hasattr(entry, attribute):
            attribute_val = getattr(entry, attribute)
            display.vvv("keepass: Attribute '{attribute}' found in static properties of '{path}'")
        else:
            attribute_val = entry.get_custom_property(attribute)
            if attribute_val is not None:
                display.vvv(
                    "keepass: Attribute '{attribute}' found in custom properties of '{path}'"
                )

        if attribute_val is None:
            raise AnsibleError(f"'{attribute}' not found in '{path}'")
        else:
            return attribute_val

    def find_entry(self, path: str) -> KeepassEntry:
        """
        Find the entry matching the path and return the entry

        Args:
          path: The full path of the entry including the entry name

        Raises:
          AnsibleError: This exception is raised for:
            - The path parameter does not start with /
            - The entry is not found
            - Duplicate entries are found
            - Path mistmatch, the path expected is not what the entry found returns

        Returns:
          KeepassEntry: The entry that matches the path
        """

        # Get the group from the path
        group = self.find_group(path)
        group_path_str = "/".join([""] + group.path)

        group_entries = ["/".join([""] + g.path) for g in group.entries]
        display.vvv(
            f"keepass: All entries in group '{group_path_str}': {group_entries}"
        )

        # Check for existence of the entry and any duplicates
        entry_index = None
        # Check for existence of the entry
        try:
            entry_index = group_entries.index(path)
        except ValueError:
            raise AnsibleError(f"Entry not found under path: {path}")

        # Check for duplicates of the entry within the group. We only care if the entry
        # we are searching for has duplicates. Other entries that are duplicated are
        # not checked.
        try:
            group_entries.index(path, entry_index + 1)
            raise AnsibleError(f"Duplicate entries found under path: {path}")
        except ValueError:
            # We do not raise here because duplicate entry not found
            pass

        entry = group.entries[entry_index]

        entry_path = "/".join([""] + entry.path)

        if entry_path != path:
            raise AnsibleError(
                f"Path mismatch, found '{entry_path}' instead of '{path}'"
            )

        display.vvv(
            f"keepass: Found entry in path '{entry_path}'. UUID: {entry.uuid.hex.upper()}"
        )

        return entry

    def find_group(self, path: str) -> KeepassGroup:
        """
        Find the group matching the path and return the group entry

        Args:
          path: The full path of the entry include the entry name

        Raises:
          AnsibleError: This exception is raised for:
            - The path parameter does not start with /
            - The group is not found
            - Duplicate groups are found

        Returns:
          KeepassGroup: The group entry that matches the path
        """
        if not path.startswith("/"):
            raise AnsibleError(f"Path should start with '/'. Fix entry: {path}")

        all_groups = ["/".join([""] + g.path) for g in self.keepass.groups]
        display.vvv(f"keepass: Groups found in database: {all_groups}")

        search_group = "/".join(path.split("/")[:-1])
        display.vvv(f"keepass: Searching for group: '{search_group}'")

        # Check for duplicate groups
        # Check for existence of the group and any duplicates
        first_group_index = None
        # Check for group existence
        try:
            first_group_index = all_groups.index(search_group)
        except ValueError:
            raise AnsibleError(f"Group not found under path: {search_group}")

        # Check for duplicates at the group level. We only care if the group we are
        # searching for has duplicates. Other groups that are duplicated are not
        # checked.
        try:
            all_groups.index(search_group, first_group_index + 1)
            raise AnsibleError(f"Duplicate groups found under path: {search_group}")
        except ValueError:
            # We do not raise here because duplicate group not found
            pass

        group = self.keepass.groups[first_group_index]

        display.vvv(f"keepass: Found group in path {search_group}")

        return group

    def run(self, terms: list, variables=None, **kwargs) -> list:
        inventory_dir = variables.get("inventory_dir", None)
        default_keepass_dbx_path = os.path.realpath(os.path.join(inventory_dir, ".keepass-vault.kdbx"))
        # First of all populate options,
        # this will already take into account env vars and ini config
        self.set_options(var_options=variables, direct=kwargs)
        display.vvv(f"{self.get_options()}")

        # lookups in general are expected to both take a list as input and output a list
        # this is done so they work with the looping construct 'with_'.
        ret = []

        # Set data from Ansible variables
        keepass_dbx = variables.get("keepass_dbx", default_keepass_dbx_path)
        kp_psw = variables.get("keepass_psw", None)
        kp_psw_file = variables.get("keepass_psw_file", None)
        kp_keyfile = variables.get("keepass_key_file", None)

        # Validate terms and extract values and assign to local variables
        if len(terms) < 2 or len(terms) > 3:
            raise AnsibleError("Invalid number of options provided")
        entry_path = terms[0]
        entry_attribute = terms[1]

        # Print out some debug data
        display.vvv("keepass: database file: '%s'" % keepass_dbx)
        display.vvv("keepass: looking from entry path: '%s'" % entry_path)
        display.vvv("keepass: looking up attribute: '%s'" % entry_attribute)

        if keepass_dbx is None:
            raise AnsibleError("keepass_dbx has to be defined.")
        else:

            keepass_dbx = os.path.realpath(os.path.expanduser(keepass_dbx))
            if not os.path.isfile(keepass_dbx):
                raise AnsibleError("keepass_dbx: %s is not a file" % keepass_dbx)

        if kp_psw_file is not None:
            kp_psw_file = os.path.realpath(os.path.expanduser(kp_psw_file))
            if os.path.isfile(kp_psw_file):
                display.vvv("keepass: password file: %s" % kp_psw_file)
                with open(kp_psw_file, "r+") as kp_psw_file_fp:
                    kp_psw = kp_psw_file_fp.read().strip()
            else:
                raise AnsibleError("kp_psw_file: %s is not a file" % kp_psw_file)

        if kp_keyfile is not None:
            kp_keyfile = os.path.realpath(os.path.expanduser(kp_keyfile))

        self.keepass = pykeepass.PyKeePass(filename=keepass_dbx, password=kp_psw, keyfile=kp_keyfile)
        entry = self.get_entry_attribute(entry_path, entry_attribute)

        return [entry]
