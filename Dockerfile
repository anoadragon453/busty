# To build the image, run `docker build` command from the root of the
# repository:
#
#    docker build -t busty -f Dockerfile .
#
# There is an optional PYTHON_VERSION build argument which sets the
# version of python to build against. For example:
#
#    docker build -t busty -f Dockerfile --build-arg PYTHON_VERSION=3.10 .
#

ARG PYTHON_VERSION=3.10
FROM docker.io/python:${PYTHON_VERSION}-alpine

# Install any dependencies. We do this before copying the source code
# such that these dependencies can be cached.
# This speeds up subsequent image builds when the source code is changed

# Install any native runtime dependencies
RUN apk add --no-cache \
    # needed for working with downloaded song files
    ffmpeg \
    # needed for building the ffmpeg python module
    musl-dev libffi-dev gcc

# Install python runtime modules
COPY requirements.txt /src/requirements.txt
RUN pip install -r "/src/requirements.txt"

# Now copy the source code
COPY *.py /src/

# Specify a volume that holds persistent data (such as songs)
VOLUME ["/data"]

# Configure busty to use this directory
ENV BUSTY_ATTACHMENT_DIR=/data/attachments

# Print logs as soon as they're emitted from the bot, rather than buffering them
ENV PYTHONUNBUFFERED=1

# Start busty
ENTRYPOINT ["python", "/src/main.py"]
