# Upstream regression replay

Each case switches official wheels in a new isolated environment while the test source stays unchanged. Installation is offline; sources and SHA256 hashes are in assets/manifest.json.

| Case | Version change | Exit code broken → fixed | Result |
|---|---|---|---|
| [Pre-release wrongly excluded by a specifier](https://github.com/pypa/packaging/issues/788) | 24.1 → 24.2 | 1 → 0 | reproduced |
| [Untagged Python version breaks marker evaluation](https://github.com/pypa/packaging/issues/678) | 24.1 → 24.2 | 1 → 0 | reproduced |
| [Command help omits an empty-string default](https://github.com/pallets/click/issues/2500) | 8.1.7 → 8.1.8 | 1 → 0 | reproduced |
| [Command help shows the wrong default from default_map](https://github.com/pallets/click/issues/2632) | 8.1.7 → 8.1.8 | 1 → 0 | reproduced |

These are minimal reproductions of specific upstream defects. They do not represent independent projects, the distribution of faults or developer time. The replay knows the fixed version; the product never guesses versions for other errors. No model was trained on these cases.
