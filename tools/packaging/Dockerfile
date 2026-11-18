FROM python:3.14.10-slim-bookworm@sha256:1faf2343e747208b2a36e5f2b5ff908ec3b2d0078a6a7bfe73b535698fe83909

RUN apt-get update \
    && apt-get install -y --no-install-recommends binutils=2.40-2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/packaging-requirements.txt
RUN python3 -m pip install --no-cache-dir --only-binary=:all: --require-hashes \
    -r /tmp/packaging-requirements.txt
