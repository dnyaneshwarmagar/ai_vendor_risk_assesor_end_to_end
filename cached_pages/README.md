# Cached vendor pages (M2 demo)

JSON snapshots of real-vendor pages used when `VRA_PAGE_CACHE=1`.
Each file is named `<sha256(url)[:24]>.json` with `{url, title, text, published_date}`.

Re-fetch and overwrite these after hand-checking trust centres so demos do not depend on the live internet.
