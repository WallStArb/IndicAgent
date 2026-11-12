"""Push the ingress rules in production/cloudflare/tunnels.yml to Cloudflare.

Remotely managed tunnels take their rules from Cloudflare, so the repo file is the source of
truth and this script is the only writer. The API token needs the Cloudflare Tunnel Edit
permission and lives in a root-only file (default ~/.cloudflare/api_token), never in the repo.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
API = "https://api.cloudflare.com/client/v4/accounts/{account}/cfd_tunnel/{tunnel}/configurations"


def _call(method: str, url: str, token: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        url,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if not payload.get("success"):
        raise SystemExit(f"Cloudflare API error: {payload.get('errors')}")
    return payload["result"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tunnels", nargs="*", help="tunnel names (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="show the diff, write nothing")
    parser.add_argument("--token-file", type=Path, default=Path.home() / ".cloudflare/api_token")
    args = parser.parse_args()

    spec = yaml.safe_load((REPO / "production/cloudflare/tunnels.yml").read_text())
    token = args.token_file.read_text().strip()
    names = args.tunnels or list(spec["tunnels"])
    for name in names:
        tunnel = spec["tunnels"][name]
        url = API.format(account=spec["account_id"], tunnel=tunnel["id"])
        live = _call("GET", url, token)["config"] or {}
        want = {**live, "ingress": tunnel["ingress"]}
        if live.get("ingress") == want["ingress"]:
            print(f"{name}: in sync")
            continue
        print(f"{name}: live {len(live.get('ingress', []))} rules -> repo {len(want['ingress'])}")
        if not args.dry_run:
            _call("PUT", url, token, {"config": want})
            print(f"{name}: applied")


if __name__ == "__main__":
    main()
