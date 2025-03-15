from setuptools import setup, find_packages
import re

VERSIONFILE="asyncftp/_version.py"
verstrline = open(VERSIONFILE, "rt").read()
VSRE = r"^__version__ = ['\"]([^'\"]*)['\"]"
mo = re.search(VSRE, verstrline, re.M)
if mo:
    verstr = mo.group(1)
else:
    raise RuntimeError("Unable to find version string in %s." % (VERSIONFILE,))

setup(
	# Application name:
	name="asyncftp",

	# Version number (initial):
	version=verstr,

	# Application author details:
	author="Tamas Jos",
	author_email="info@skelsecprojects.com",

	# Packages
	packages=find_packages(exclude=["tests*"]),

	# Include additional files into the package
	include_package_data=True,
	license="MIT",

	# Details
	url="https://github.com/skelsec/asyncftp",

	zip_safe = False,
	#
	# license="LICENSE.txt",
	description="Asynchronous FTP client implementation",

	# long_description=open("README.txt").read(),
	python_requires='>=3.7',
	install_requires=[
		'asyauth>=0.0.16',
		'asysocks>=0.2.9',
		'prompt-toolkit>=3.0.2',
		'tqdm',
		'colorama',
		'wcwidth',
	],
	
	classifiers=[
		"Programming Language :: Python :: 3.7",
		"Operating System :: OS Independent",
	],
	entry_points={
		'console_scripts': [
			'asyncftp-client = asyncftp.examples.ftpclient:main',
		],

	}
)