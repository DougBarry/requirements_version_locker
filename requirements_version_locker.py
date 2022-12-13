#!/usr/bin/env python
import pathlib
from urllib.request import urlopen
import pkg_resources
import json
import logging
import sys
import argparse


class Package:

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
        try:
            with pathlib.Path(requirements_file).open('r') as requirements_txt:
                install_requires = []
                for requirement in pkg_resources.parse_requirements(requirements_txt):
                    install_requires.append(requirement)

        except Exception as ex:
            self.log.error(f"Unable to parse requirements file: '{requirements_file}' using importlib. Check format.")
            return None

        return install_requires

    def get_package_details_from_api(self, package_name: str, package_version: str) -> Package:

        json_api_url = f"https://pypi.org/pypi/{package_name}/{package_version}/json"
        try:
            with urlopen(json_api_url) as f:
                data = json.load(f)
        except Exception as ex:
            self.log.error(f"Unable to connect to PyPi AP endpoint: {json_api_url}'")
            raise ex

        data_dict = {}

        try:
            data_dict = data["urls"]
        except KeyError as ke:
            self.log.debug("Unable to find 'urls' element in PyPi JSON response")
            raise Exception(f"Package '{package_name}=={package_version}' hash information retrieval failed")

        hashes = []
        for source in data_dict:
            hashes.append(source["digests"]["sha256"])

        return Package(package_name, package_version, hashes)

    def write_requirements_file(self, output_file: str, output_packages: str, overwrite: bool = True) -> bool:
        if pathlib.Path(output_file).exists():
            if not overwrite:
                raise FileExistsError(f'{output_file} exists and overwrite option not specified')

        self.log.debug(f"Writing new requirements file to '{output_file}'")
        with pathlib.Path(output_file).open('w') as requirements_new_txt:
            for package in output_packages:
                requirements_new_txt.write(f'{str(package)}\n')

    def run(self, input_file: str, output_file: str, overwrite_mode: bool = False) -> int:

        self.log.info('Assessing packages')
        try:
            input_packages = self.get_required_packages(input_file)
        except Exception as ex:
            self.log.exception(ex)
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
                self.log.exception(ex)
                return 1

        self.log.info(f'Writing new hash locked requirements to {output_file}')

        try:
            self.write_requirements_file(output_file, output_packages, overwrite_mode)
        except Exception as ex:
            self.log.exception(ex)
            return 1

        return 0


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    sys.argv.extend([
        "-i", "requirements.txt",
        "-o", "newreq2.txt",
        # "-O",
        # "-v"
        # "-h"
    ])

    # needs argparse
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
