import re
from urllib.parse import urljoin, urlsplit

def _filename(url: str) -> str:
    return urlsplit(url).path.rsplit("/", 1)[-1]

def _variants(master_text: str, master_url: str) -> list[tuple[int, str]]:
    """(bandwidth, absolute URL) for each stream a master playlist offers."""
    variants = []
    bw = None
    for line in master_text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            m = re.search(r"BANDWIDTH=(\d+)", line)
            bw = int(m.group(1)) if m else 0
        elif line and not line.startswith("#"):
            variants.append((bw or 0, urljoin(master_url, line)))
            bw = None
    if not variants:
        raise ValueError("no variants in master playlist")
    return variants

def pick_variant(master_text: str, master_url: str, quality: str) -> tuple[str, int]:
    """(URL, bandwidth in bits per second) of the stream for the chosen quality.
    The bandwidth is 0 when the playlist doesn't state one."""
    variants = _variants(master_text, master_url)
    if quality == "highest":
        bw, url = max(variants, key=lambda v: v[0])
        return url, bw
    for bw, url in variants:
        if quality in _filename(url):
            return url, bw
    raise ValueError(f"quality {quality} not found in master")

def pick_from_master(master_text: str, master_url: str, quality: str) -> str:
    return pick_variant(master_text, master_url, quality)[0]

def _bitrate_in_url(url: str) -> int:
    m = re.search(r"(\d+)k\.m3u8", url)
    return int(m.group(1)) if m else 0

def pick_from_urls(urls: list[str], quality: str) -> str:
    if quality == "highest":
        return max(urls, key=_bitrate_in_url)
    for url in urls:
        if quality in _filename(url):
            return url
    raise ValueError(f"quality {quality} not found in captured urls: {urls}")
