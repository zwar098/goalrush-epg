FROM python:3.12-slim

# tzdata gives Python's zoneinfo access to the IANA timezone database
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY generate_epg.py /app/generate_epg.py
COPY run_forever.py /app/run_forever.py

RUN mkdir -p /output

VOLUME ["/output"]

ENTRYPOINT ["python3", "/app/run_forever.py"]
