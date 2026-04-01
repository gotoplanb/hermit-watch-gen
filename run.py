#!/usr/bin/env python3
"""Hermit Watch state generator entrypoint.

Reads config.yml, fetches status from public APIs, and writes
one JSON file per source into sources/.
"""

import sys

import yaml

from generators.base import fetch_json, stale_source, write_source
from generators.statuspage import get_state

GENERATOR_MAP = {
    "statuspage": get_state,
}


def main() -> int:
    with open("config.yml") as f:
        config = yaml.safe_load(f)

    sources = config.get("sources", {})

    # Deduplicate API URLs — fetch each unique URL once
    url_cache: dict[str, dict] = {}
    errors = 0

    for filename, src in sources.items():
        generator_name = src["generator"]
        if generator_name not in GENERATOR_MAP:
            print(f"[{filename}] Unknown generator: {generator_name}")
            errors += 1
            continue

        api_url = src["api_url"]
        display_name = src["display_name"]
        source_url = src.get("url")
        component = src.get("component")

        # Fetch with deduplication
        if api_url not in url_cache:
            try:
                url_cache[api_url] = fetch_json(api_url)
                print(f"[fetch] {api_url}")
            except Exception as e:
                print(f"[{filename}] Fetch failed: {e}")
                url_cache[api_url] = None

        api_response = url_cache[api_url]

        if api_response is None:
            stale_source(filename, "calm", f"Failed to fetch {api_url}",
                         display_name=display_name, url=source_url)
            errors += 1
            continue

        try:
            state, message = GENERATOR_MAP[generator_name](api_response, component)
            write_source(filename, state, display_name, message=message, url=source_url)
            print(f"[{filename}] {state}")
        except Exception as e:
            print(f"[{filename}] Generator error: {e}")
            stale_source(filename, "calm", str(e),
                         display_name=display_name, url=source_url)
            errors += 1

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
