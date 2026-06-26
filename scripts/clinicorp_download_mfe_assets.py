import json
import re
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError


OUT = Path(r"C:\tmp\clinicorp_assets")
MANIFESTS = {
    "gc": "https://storage.googleapis.com/prod-clinicorp-mfe/gc/current/mf-manifest.json",
    "financial": "https://storage.googleapis.com/prod-clinicorp-mfe/financial/current/mf-manifest.json",
    "shell-home": "https://storage.googleapis.com/prod-clinicorp-mfe/shell-home/current/mf-manifest.json",
    "cdam": "https://storage.googleapis.com/prod-clinicorp-mfe/cdam/current/mf-manifest.json",
    "security": "https://storage.googleapis.com/prod-clinicorp-mfe/security/current/mf-manifest.json",
}


def fetch_json(url):
    with request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size:
        return
    try:
        with request.urlopen(url, timeout=60) as resp:
            path.write_bytes(resp.read())
    except (HTTPError, URLError) as exc:
        print(f"falhou {url}: {exc}", flush=True)


def iter_asset_paths(manifest):
    for section in ("shared", "exposes"):
        for item in manifest.get(section, []):
            assets = item.get("assets", {})
            for kind in ("js", "css"):
                for mode in ("sync", "async"):
                    for asset in assets.get(kind, {}).get(mode, []):
                        yield asset


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for name, url in MANIFESTS.items():
        manifest = fetch_json(url)
        base = manifest["metaData"]["publicPath"]
        (OUT / f"{name}-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for asset in sorted(set(iter_asset_paths(manifest))):
            if not asset.endswith(".js"):
                continue
            asset_url = base + asset
            path = OUT / name / Path(asset).name
            download(asset_url, path)
            downloaded += 1

            # Pull direct relative imports from the downloaded module.
            text = path.read_text(encoding="utf-8", errors="ignore")
            for rel in sorted(set(re.findall(r'from\s+"(\./[^"]+\.js)"', text))):
                rel_url = base + "assets/" + rel.removeprefix("./")
                rel_path = OUT / name / Path(rel).name
                download(rel_url, rel_path)
                downloaded += 1

    print(f"assets_baixados={downloaded}")
    print(str(OUT))


if __name__ == "__main__":
    main()
