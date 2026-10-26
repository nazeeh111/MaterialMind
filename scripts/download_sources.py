"""Fetch pinned public CC BY 4.0 data with checksums and atomic finalization."""
import argparse
import hashlib
from pathlib import Path
import urllib.request

INPUTS = {
    "wbm-initial.jsonl.gz": ("53161835", "b809f101dd42a745ec2baabe7eb16f11"),
    "wbm-summary.csv.gz": ("64706751", "1555268d3aa59d20262cb9d01ce0994b"),
    "chgnet.csv.gz": ("66646268", "fd7cd3781a24be465aaeadf97663ce58"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    for name, (fid, expected) in INPUTS.items():
        output = args.destination / name
        if output.exists():
            if hashlib.md5(output.read_bytes()).hexdigest() != expected:
                raise SystemExit(f"Existing file failed checksum; preserved for inspection: {output}")
            print(f"Verified existing {name}")
            continue
        temporary = output.with_suffix(output.suffix + ".part")
        request = urllib.request.Request(f"https://ndownloader.figshare.com/files/{fid}", headers={"User-Agent": "MaterialMind/0.1.0 research downloader"})
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as stream:
            if response.status != 200:
                raise RuntimeError(f"Download returned {response.status}; no file accepted")
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        if hashlib.md5(temporary.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Downloaded file failed checksum: {temporary}")
        temporary.replace(output)
        print(f"Verified {name}: {output.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
