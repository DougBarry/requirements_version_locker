#!/usr/bin/env python
"""
Doug Barry @ UoG 20221213
Idea from: https://gitlab.com/pdebelak/dotfiles/-/blob/83082cd567f5edd4da90d2297246af9c42b98397/scripts/pip-hash-freeze
and blog post: https://www.peterdebelak.com/blog/generating-a-fully-qualified-and-hashed-requirements-file/
"""

import pathlib
from urllib.request import urlopen
import pkg_resources
import json
import logging
import sys
import argparse


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

    def __str__(self) -> str:
        package_text = f'{self.name}=={self.version}'
        for phash in self.hashes:
            package_text += f'{self.__newline}--hash=sha256:{phash}'
        return package_text


class RequirementsVersionLocker:
    """
    A class module which 'freezes' requirements.txt files with a specified version, adding package hash information.
    """

    _logger: logging.Logger

    def __init__(self, verbose_mode=False):
        self._logger = logging.getLogger(__class__.__name__)
        self._logger.setLevel(logging.INFO)
        if verbose_mode:
            self._logger.setLevel(logging.DEBUG)

    def _log_get(self) -> logging.Logger:
        return self._logger

    log = property(
        fget=_log_get,
        doc="Instance logger"
    )

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
            self.log.error(f"Unable to connect to PyPi AP endpoint: {json_api_url}'")
            self.log.debug(ex)
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

    def write_requirements_file(self, output_file: str, output_packages: str, overwrite: bool = True) -> bool:
        """
        Write a new requirements file with package hash information in correct format for pip
        """

        if pathlib.Path(output_file).exists():
            if not overwrite:
                raise FileExistsError(f"'{output_file}' exists and overwrite option not specified")

        self.log.info(f"Writing new requirements file to '{output_file}'")
        with pathlib.Path(output_file).open('w') as requirements_new_txt:
            for package in output_packages:
                requirements_new_txt.write(f'{str(package)}\n')

    def run(self, input_file: str, output_file: str, overwrite_mode: bool = False) -> int:
        """
        Run this module
        """

        if not pathlib.Path(input_file).exists():
            self.log.error(f"File '{input_file}' does not exist")
            return 1

        self.log.info('Assessing packages')
        try:
            input_packages = self.get_required_packages(input_file)
        except Exception as ex:
            self.log.error(f"Error assessing packages from '{input_file}'")
            self.log.debug(ex)
            return 1

        if not input_packages:
            self.log.error("Unable to load input file")
            return 1

        output_packages = []

        self.log.info('Gathering hash information')
        for package in input_packages:
            try:
                output_packages.append(self.get_package_details_from_api(str(package.name),str(package.specs[0][1])))
            except Exception as ex:
                self.log.debug(ex)
                return 1

        self.log.info(f'Writing new hash locked requirements to {output_file}')

        try:
            self.write_requirements_file(output_file, output_packages, overwrite_mode)
        except FileExistsError as fee:
            self.log.info(f"Writing failed: {fee.args[0]}")
            return 1
        except Exception as ex:
            self.log.exception(ex)
            return 1

        return 0


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

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
        "-v", "--verbose", action=argparse.BooleanOptionalAction, dest="verbose_mode", required=False,
        help="Enable verbose output", default=False
    )

    args = parser.parse_args()

    app = RequirementsVersionLocker(verbose_mode=args.verbose_mode)

    exit(
        app.run(
            input_file=args.input_file,
            output_file=args.output_file,
            overwrite_mode=args.overwrite_mode
        )
    )
