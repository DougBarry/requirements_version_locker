#!/usr/bin/env python
"""
Doug Barry @ UoG 20221213
Idea from: https://gitlab.com/pdebelak/dotfiles/-/blob/83082cd567f5edd4da90d2297246af9c42b98397/scripts/pip-hash-freeze
and blog post: https://www.peterdebelak.com/blog/generating-a-fully-qualified-and-hashed-requirements-file/
"""
import os
import errno
import pathlib
import subprocess
from typing import Any
from urllib.request import urlopen
import pkg_resources
import json
import logging
import sys
import argparse
from datetime import datetime

class Package:
    """
    A class holding a simplified representation of a python package in PyPi
    """

    name: str
    version: str
    hashes: []

    __newline: str = " \\\n    "

    def __init__(self, name: str, version: str, hashes: []):
        self.name = name
        self.version = version
        self.hashes = hashes

    def get_file_lines(self) -> str:
        package_text = f'{self.name}=={self.version}'
        for phash in self.hashes:
            package_text += f'{self.__newline}--hash=sha256:{phash}'
        return package_text

    def __str__(self) -> str:
        return f'{self.name}=={self.version}'


class RequirementsVersionLocker:
    """
    A class module which 'freezes' requirements.txt files with a specified version, adding package hash information.
    """

    @property
    def log(self) -> logging.Logger:
        return self._logger

    def __init__(self, app_config: dict):
        self._logger: logging.Logger = None
        self.__config: dict = {}
        self.ignore_errors: bool
        self.overwrite_mode: bool
        self.verbose_mode: bool

        self._logger = logging.getLogger(__class__.__name__)
        self._logger.setLevel(logging.INFO)

        if not app_config:
            raise ValueError('Configuration values not supplied')

        self.__config = app_config

    def config(self, key: Any, default: Any = None) -> Any:
        if not self.__config:
            raise ValueError("Configuration not defined")
        return self.__config.get(key, default)

    def config_require(self, key: Any) -> Any:
        if key not in self.__config.keys():
            raise KeyError(f'Configuration did not contain key: {key}')
        return self.__config.get(key)

    def get_required_packages(self, requirements_file: str) -> list:
        """
        Open a requirements file and gather pacakge and version information
        """
        try:
            self.log.debug(f"Opening requirements file '{requirements_file}'")
            with pathlib.Path(requirements_file).open('r') as requirements_txt:
                install_requires = []
                for requirement in pkg_resources.parse_requirements(requirements_txt):
                    self.log.debug(f"Found requirement '{str(requirement)}'")
                    install_requires.append(requirement)
        except Exception as ex:
            self.log.error(f"Unable to parse requirements file: '{requirements_file}' "
                           f"using pkg_resources. Check format.")
            self.log.debug(ex)
            return None

        self.log.debug(f"Total requirement count: {len(install_requires)}")

        return install_requires

    def get_package_details_from_api(self, package_name: str, package_version: str) -> Package:
        """
        Retrieve json from PyPi describing package at this version
        """

        json_api_url = f"https://pypi.org/pypi/{package_name}/{package_version}/json"
        self.log.debug(f"Getting package details using using JSON URL: '{json_api_url}'")

        # Certifi might be a good idea here, but it is another dependency
        try:
            with urlopen(json_api_url) as f:
                data = json.load(f)
                self.log.debug(f"JSON data returned: '{data}'")
        except Exception as ex:
            self.log.warning(f"Unable to connect to PyPi AP endpoint: {json_api_url}'. Exception: '{ex}'")
            raise ex

        data_dict = {}

        try:
            data_dict = data["urls"]
        except KeyError as ke:
            self.log.debug(f"Unable to find 'urls' element in PyPi JSON response. Hash retrieval not possible for "
                           f"package '{package_name}=={package_version}'")
            raise FileNotFoundError(f"Package '{package_name}=={package_version}' hash information retrieval failed")

        hashes = []
        for source in data_dict:
            hashes.append(source["digests"]["sha256"])

        self.log.debug(f"Retrieved {len(hashes)} hashes for package '{package_name}=={package_version}'")

        if len(hashes) < 1:
            self.log.error(f"Retrieve hash count for package '{package_name}=={package_version}' was zero")
            raise IndexError(f"Package '{package_name}=={package_version}' hash count was zero")

        return Package(package_name, package_version, hashes)

    def get_requirements_file_header(self):
        """
        Return a string to be used as a header for the generated requirements file
        """
        cfg: str = ""
        for key in self.__config:
           cfg+=f"#\t{key}: {self.__config[key]}\n"

        return f'#\n' \
               f'# This file was generated by requirements_version_locker.py.\n# See ' \
               f'https://github.com/DougBarry/requirements_version_locker.\n#\n' \
               f'# Generation config:\n' \
               f'{cfg}#\n' \
               f'# Generation timestamp: {datetime.now().isoformat()}\n#\n'

    def get_requirements_file_footer(self, skipped_packages):
        """
        Return a string to be used as a footer for the generated requirements file
        """
        if not skipped_packages:
            return ''

        pkgs: str = ""
        for pkg in skipped_packages:
            pkgs += f"#\t{pkg}\n"

        return f'#\n' \
               f'# WARNING: Some packages were not pinned, possible due to version information not being available, or ' \
               f'installed libraries\n being provided by the host OS are customised.\n' \
               f'#\n' \
               f'{pkgs}'

    def write_requirements_file(self, output_file: str, output_packages: list, skipped_pacakges: list) -> bool:
        """
        Write a new requirements file with package hash information in correct format for pip. This will overwrite
        any existing file
        """

        with pathlib.Path(output_file).open('w') as requirements_new_txt:
            requirements_new_txt.write(self.get_requirements_file_header())
            for package in output_packages:
                if package:
                    requirements_new_txt.write(f'{package.get_file_lines()}\n')
            requirements_new_txt.write(self.get_requirements_file_footer(skipped_pacakges))
        return True

    def run(self) -> int:
        """
        Run this module
        """

        if self.config('verbose_mode'):
            self.log.setLevel(logging.DEBUG)

        self.verbose_mode = self.config('verbose_mode', False)
        self.overwrite_mode = self.config('overwrite_mode', False)
        self.ignore_errors = self.config('ignore_errors', False)

        input_file = self.config_require('input_file')
        output_file = self.config_require('output_file')

        if not pathlib.Path(input_file).exists():
            self.log.fatal(f"File '{input_file}' does not exist")
            return errno.ENOENT

        if pathlib.Path(output_file).exists():
            if not self.overwrite_mode:
                self.log.fatal(f"'{output_file}' exists and overwrite option not specified")
                return errno.EEXIST

        self.log.info('Assessing packages')
        try:
            input_packages = self.get_required_packages(input_file)
        except Exception as ex1:
            self.log.error(f"Error assessing packages from '{input_file}'")
            self.log.debug(ex1)
            return errno.EIO

        if not input_packages:
            self.log.error("Unable to load input file")
            return errno.EIO

        output_packages = []
        skipped_packages = []

        self.log.info('Gathering hash information')
        for package in input_packages:
            try:
                details = self.get_package_details_from_api(str(package.name), str(package.specs[0][1]))
                output_packages.append(details)
            except Exception as ex1:
                skipped_packages.append(f"{package.name}=={package.specs[0][1]}")
                if not self.ignore_errors:
                    self.log.fatal(ex1)
                    return 1
                self.log.debug(ex1)

        self.log.info(f"Writing new hash locked requirements to '{output_file}'")

        try:
            if not self.write_requirements_file(output_file, output_packages, skipped_packages):
                self.log.error(f"Unable to write requirements file '{output_file}'")
        except FileExistsError as fee:
            self.log.error(f"Writing failed: {fee.args[0]}")
            return 1
        except Exception as ex1:
            self.log.exception(ex1)
            return 1

        self.log.info(f"Successfully wrote file.")
        return 0


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i", "--input-file", type=str, dest="input_file", required=True,
        help="Input requirements file without hashes", default="requirements.txt",
    )
    parser.add_argument(
        "-o", "--output-file", type=str, dest="output_file", required=True,
        help="Output requirements file with hash values", default="requirements-hash-locked.txt",
    )
    parser.add_argument(
        "-O", "--overwrite", action=argparse.BooleanOptionalAction, dest="overwrite_mode", required=False,
        help="Overwrite output file if it exists", default=False
    )
    parser.add_argument(
        "-q", "--ignore-errors", action=argparse.BooleanOptionalAction, dest="ignore_errors", required=False,
        help="Ignore missing packages on PyPi", default=False
    )
    parser.add_argument(
        "-v", "--verbose", action=argparse.BooleanOptionalAction, dest="verbose_mode", required=False,
        help="Enable verbose output", default=False
    )

    args = parser.parse_args()

    config = dict()
    config['verbose_mode'] = args.verbose_mode
    config['input_file'] = args.input_file
    config['output_file'] = args.output_file
    config['overwrite_mode'] = args.overwrite_mode
    config['ignore_errors'] = args.ignore_errors

    app = RequirementsVersionLocker(config)

    result: int = 1
    try:
        result = app.run()
    except Exception as ex:
        logging.exception(ex)
        result = 1

    exit(result)
