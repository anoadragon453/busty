#!/bin/sh
#
# Runs linting scripts over the local checkout. Can be run as:
# ./lint.sh
# to lint all project files, or as:
# ./lint.sh file.py directory file2.py
# to lint specific files and directories.
#
# List of commands that are run:
# isort - sorts import statements
# flake8 - lints and finds mistakes
# black - opinionated code formatter

set -e

if [ $# -ge 1 ]
then
    files=$*
  else
    files=src/*.py
fi

echo "Linting these locations: $files"
isort $files
flake8 $files
python3 -m black $files
