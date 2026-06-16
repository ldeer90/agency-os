"""Publish a static Agency Health Dashboard snapshot to a cPanel subdomain."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard.api.data import dashboard_payload


WEB_DIR = ROOT / "dashboard" / "web"
WEB_DIST = WEB_DIR / "dist"
PACKAGE_DIR = ROOT / "dist-dashboard-subdomain"
PAYLOAD_NAME = "dashboard-payload.json"
LOCAL_SECRET_DIR = ROOT / ".secrets"
LOCAL_AUTH_CREDENTIALS = LOCAL_SECRET_DIR / "dashboard-basic-auth.json"

DEFAULT_ENV_FILES = [
    ROOT / ".env.local",
    ROOT / ".env",
    ROOT.parent / "seo-reporting-platform" / ".env.local",
]
DEFAULT_DOMAIN = "laurencedeer.com.au"
DEFAULT_RECORD = "dashboard"
DEFAULT_IP = "50.63.142.110"
DEFAULT_REMOTE_USER = "ncymgm552z9f"
DEFAULT_REMOTE_HOST = "50.63.142.110"
DEFAULT_REMOTE_DIR = "/home/ncymgm552z9f/public_html/dashboard"
DEFAULT_REMOTE_HTPASSWD = "/home/ncymgm552z9f/.dashboard_htpasswd"
DEFAULT_SSH_KEY = "~/.ssh/godaddy_ldseo_id_rsa"
DEFAULT_PUBLIC_BASE_URL = "https://dashboard.laurencedeer.com.au"
DEFAULT_AUTH_USERNAME = "laurence"
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without mutating DNS or server files")
    parser.add_argument("--skip-upload", action="store_true", help="Build/package locally but do not upload")
    parser.add_argument("--skip-dns", action="store_true", help="Do not create or update the GoDaddy DNS record")
    parser.add_argument("--skip-cpanel", action="store_true", help="Do not create/check the cPanel subdomain")
    parser.add_argument("--skip-build", action="store_true", help="Use existing dashboard/web/dist output")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    load_env_files(DEFAULT_ENV_FILES)
    config = publish_config()
    result: dict[str, Any] = {
        "ok": False,
        "dryRun": args.dry_run,
        "target": {
            "dns": f"{config['record']}.{config['domain']} -> {config['ip']}",
            "remoteDir": config["remote_dir"],
            "publicBaseUrl": config["public_base_url"],
        },
        "steps": [],
    }

    if args.dry_run:
        result["steps"].extend(
            [
                {"planned": "export_static_payload", "path": display_path(WEB_DIR / "public" / PAYLOAD_NAME)},
                {"planned": "build_static_dashboard", "cwd": display_path(WEB_DIR), "skipBuild": args.skip_build},
                {"planned": "package_dashboard", "source": display_path(WEB_DIST), "output": display_path(PACKAGE_DIR)},
                {"planned": "ensure_basic_auth", "credentialsPath": display_path(LOCAL_AUTH_CREDENTIALS), "remoteHtpasswd": config["remote_htpasswd"]},
            ]
        )
        if not args.skip_dns:
            result["steps"].append({"planned": "ensure_dns", "record": result["target"]["dns"]})
        if not args.skip_cpanel:
            result["steps"].append({"planned": "ensure_cpanel_subdomain", "remoteDir": config["remote_dir"]})
        if not args.skip_upload:
            result["steps"].append({"planned": "rsync_upload", "source": display_path(PACKAGE_DIR), "remoteDir": config["remote_dir"]})
        result["ok"] = True
        print_result(result, as_json=args.json)
        return 0

    result["steps"].append(export_static_payload())
    if not args.skip_build:
        result["steps"].append(build_dashboard())
    auth = load_or_create_basic_auth(config)
    result["steps"].append(package_dashboard(config))
    if not args.skip_dns:
        ensure_dns_record(config)
        result["steps"].append({"cmd": "GoDaddy DNS upsert", "returncode": 0, "stdout": result["target"]["dns"], "stderr": ""})
        wait_for_dns(config)
        result["steps"].append({"cmd": "DNS propagation check", "returncode": 0, "stdout": result["target"]["dns"], "stderr": ""})
    if not args.skip_cpanel:
        ensure_cpanel_subdomain(config)
        result["steps"].append({"cmd": "cPanel subdomain check", "returncode": 0, "stdout": config["remote_dir"], "stderr": ""})
    if not args.skip_upload:
        result["steps"].append(upload_htpasswd(config, auth))
        result["steps"].append(upload_package(config))
        verify_basic_auth(config["public_base_url"], auth)
        result["steps"].append({"cmd": "Live dashboard verification", "returncode": 0, "stdout": config["public_base_url"], "stderr": ""})

    result["ok"] = True
    print_result(result, as_json=args.json)
    return 0


def load_env_files(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line.removeprefix("export ").strip()
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip("'\"")


def publish_config() -> dict[str, str]:
    missing = [name for name in ["GODADDY_API_KEY", "GODADDY_API_SECRET"] if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing required local env: {', '.join(missing)}")
    return {
        "api_key": os.environ["GODADDY_API_KEY"],
        "api_secret": os.environ["GODADDY_API_SECRET"],
        "domain": os.environ.get("GODADDY_DASHBOARD_DOMAIN", DEFAULT_DOMAIN),
        "record": os.environ.get("GODADDY_DASHBOARD_RECORD", DEFAULT_RECORD),
        "ip": os.environ.get("GODADDY_DASHBOARD_IP", os.environ.get("GODADDY_REPORTS_IP", DEFAULT_IP)),
        "remote_user": os.environ.get("GODADDY_CPANEL_USER", DEFAULT_REMOTE_USER),
        "remote_host": os.environ.get("GODADDY_CPANEL_HOST", DEFAULT_REMOTE_HOST),
        "remote_dir": os.environ.get("GODADDY_DASHBOARD_REMOTE_DIR", DEFAULT_REMOTE_DIR),
        "remote_htpasswd": os.environ.get("GODADDY_DASHBOARD_HTPASSWD", DEFAULT_REMOTE_HTPASSWD),
        "ssh_key": str(Path(os.environ.get("GODADDY_SSH_KEY", DEFAULT_SSH_KEY)).expanduser()),
        "public_base_url": os.environ.get("DASHBOARD_PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL).rstrip("/"),
        "auth_username": os.environ.get("DASHBOARD_BASIC_AUTH_USERNAME", DEFAULT_AUTH_USERNAME),
    }


def export_static_payload() -> dict[str, Any]:
    public_dir = WEB_DIR / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    payload = sanitize_public_payload(dashboard_payload(force_refresh=True))
    payload.setdefault("meta", {})
    payload["meta"]["environment"] = "static"
    payload["meta"]["message"] = "Published static snapshot. Live sync controls are disabled."
    target = public_dir / PAYLOAD_NAME
    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return {"cmd": "export_static_payload", "returncode": 0, "stdout": display_path(target), "stderr": ""}


def sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_public_payload(child) for key, child in value.items()}
    if isinstance(value, list):
        return [sanitize_public_payload(child) for child in value]
    if isinstance(value, str):
        return EMAIL_PATTERN.sub("[redacted-email]", value)
    return value


def build_dashboard() -> dict[str, Any]:
    env = os.environ.copy()
    env["VITE_PUBLIC_STATIC_DASHBOARD"] = "1"
    env["VITE_DASHBOARD_DATA_URL"] = f"/{PAYLOAD_NAME}"
    return run_command(["npm", "run", "build"], WEB_DIR, env=env)


def load_or_create_basic_auth(config: dict[str, str]) -> dict[str, str]:
    LOCAL_SECRET_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if LOCAL_AUTH_CREDENTIALS.exists():
        payload = json.loads(LOCAL_AUTH_CREDENTIALS.read_text(encoding="utf-8"))
        username = str(payload.get("username") or config["auth_username"])
        password = str(payload.get("password") or "")
        if username and password:
            return {"username": username, "password": password}
    username = config["auth_username"]
    password = secrets.token_urlsafe(24)
    LOCAL_AUTH_CREDENTIALS.write_text(
        json.dumps(
            {
                "username": username,
                "password": password,
                "url": config["public_base_url"],
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    LOCAL_AUTH_CREDENTIALS.chmod(0o600)
    return {"username": username, "password": password}


def htpasswd_line(auth: dict[str, str]) -> str:
    completed = subprocess.run(
        ["openssl", "passwd", "-apr1", "-stdin"],
        input=auth["password"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("Could not create Apache password hash")
    return f"{auth['username']}:{completed.stdout.strip()}\n"


def package_dashboard(config: dict[str, str]) -> dict[str, Any]:
    if not WEB_DIST.exists():
        raise RuntimeError(f"Missing dashboard build output: {display_path(WEB_DIST)}")
    shutil.rmtree(PACKAGE_DIR, ignore_errors=True)
    shutil.copytree(WEB_DIST, PACKAGE_DIR)
    (PACKAGE_DIR / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (PACKAGE_DIR / "_headers").write_text(
        "/*\n"
        "  X-Robots-Tag: noindex, nofollow, noarchive\n"
        "  Referrer-Policy: no-referrer-when-downgrade\n",
        encoding="utf-8",
    )
    (PACKAGE_DIR / ".htaccess").write_text(
        "Options -Indexes\n"
        "ErrorDocument 404 /index.html\n\n"
        "<IfModule mod_rewrite.c>\n"
        "  RewriteEngine On\n"
        "  RewriteCond %{HTTPS} !=on\n"
        "  RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [R=301,L]\n"
        "</IfModule>\n\n"
        "<IfModule mod_headers.c>\n"
        '  Header always set X-Robots-Tag "noindex, nofollow, noarchive"\n'
        '  Header always set Referrer-Policy "no-referrer-when-downgrade"\n'
        "</IfModule>\n\n"
        'AuthType Basic\n'
        'AuthName "Agency Health Dashboard"\n'
        f"AuthUserFile {config['remote_htpasswd']}\n"
        "Require valid-user\n",
        encoding="utf-8",
    )
    return {"cmd": "package_dashboard", "returncode": 0, "stdout": display_path(PACKAGE_DIR), "stderr": ""}


def ensure_dns_record(config: dict[str, str]) -> None:
    url = f"https://api.godaddy.com/v1/domains/{config['domain']}/records/A/{config['record']}"
    body = json.dumps([{"data": config["ip"], "ttl": 600}]).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"sso-key {config['api_key']}:{config['api_secret']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status not in {200, 201, 204}:
                raise RuntimeError(f"GoDaddy DNS returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore")[:300]
        raise RuntimeError(f"GoDaddy DNS failed with HTTP {exc.code}: {detail}") from exc


def wait_for_dns(config: dict[str, str], attempts: int = 12, delay: float = 5.0) -> None:
    host = f"{config['record']}.{config['domain']}"
    answers: list[str] = []
    for _ in range(attempts):
        answers = dig(host)
        if config["ip"] in answers:
            return
        time.sleep(delay)
    raise RuntimeError(f"DNS did not resolve {host} to {config['ip']}. Last answers: {answers}")


def dig(host: str) -> list[str]:
    completed = subprocess.run(["dig", "+short", host, "A"], text=True, capture_output=True, check=False)
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def ensure_cpanel_subdomain(config: dict[str, str]) -> None:
    domain = f"{config['record']}.{config['domain']}"
    command = (
        "uapi --output=json DomainInfo domains_data 2>/dev/null | "
        "python3 -c \"import sys,json; "
        "d=json.load(sys.stdin)['result']['data']; "
        f"print(any(x.get('domain')=='{domain}' and x.get('documentroot')=='{config['remote_dir']}' for x in d.get('sub_domains',[])))\""
    )
    check = ssh(config, command)
    if check.stdout.strip().endswith("True"):
        return
    add = ssh(
        config,
        f"uapi SubDomain addsubdomain domain={config['record']} rootdomain={config['domain']} "
        f"dir={remote_dir_to_cpanel_dir(config)} disallowdot=1",
    )
    if add.returncode != 0 or "status: 1" not in add.stdout:
        raise RuntimeError(f"Failed to create cPanel subdomain: {add.stderr or add.stdout}")


def remote_dir_to_cpanel_dir(config: dict[str, str]) -> str:
    remote_dir = config["remote_dir"]
    prefix = f"/home/{config['remote_user']}/"
    if remote_dir.startswith(prefix):
        return remote_dir[len(prefix) :]
    return remote_dir


def upload_package(config: dict[str, str]) -> dict[str, Any]:
    target = f"{config['remote_user']}@{config['remote_host']}:{config['remote_dir']}/"
    cmd = [
        "rsync",
        "-az",
        "--delete",
        "--exclude=.well-known/",
        "--exclude=cgi-bin/",
        "-e",
        f"ssh -i {config['ssh_key']} -o IdentitiesOnly=yes",
        f"{PACKAGE_DIR}/",
        target,
    ]
    return run_command(cmd, ROOT)


def upload_htpasswd(config: dict[str, str], auth: dict[str, str]) -> dict[str, Any]:
    local_htpasswd = LOCAL_SECRET_DIR / "dashboard.htpasswd"
    local_htpasswd.write_text(htpasswd_line(auth), encoding="utf-8")
    local_htpasswd.chmod(0o600)
    target = f"{config['remote_user']}@{config['remote_host']}:{config['remote_htpasswd']}"
    result = run_command(
        [
            "scp",
            "-i",
            config["ssh_key"],
            "-o",
            "IdentitiesOnly=yes",
            str(local_htpasswd),
            target,
        ],
        ROOT,
    )
    chmod = ssh(config, f"chmod 644 {shell_quote(config['remote_htpasswd'])}")
    if chmod.returncode != 0:
        raise RuntimeError("Could not secure remote htpasswd file")
    result["cmd"] = "upload_htpasswd"
    result["stdout"] = config["remote_htpasswd"]
    result["stderr"] = ""
    return result


def verify_url(base_url: str) -> None:
    request = urllib.request.Request(base_url, headers={"User-Agent": "codex-dashboard-publisher"})
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status >= 400:
            raise RuntimeError(f"Live dashboard returned HTTP {response.status}")


def verify_basic_auth(base_url: str, auth: dict[str, str]) -> None:
    request = urllib.request.Request(base_url, headers={"User-Agent": "codex-dashboard-publisher"})
    try:
        urllib.request.urlopen(request, timeout=20)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise RuntimeError(f"Expected password challenge, got HTTP {exc.code}") from exc
    else:
        raise RuntimeError("Dashboard did not require a password")
    token = base64.b64encode(f"{auth['username']}:{auth['password']}".encode("utf-8")).decode("ascii")
    auth_request = urllib.request.Request(
        base_url,
        headers={"User-Agent": "codex-dashboard-publisher", "Authorization": f"Basic {token}"},
    )
    with urllib.request.urlopen(auth_request, timeout=20) as response:
        if response.status >= 400:
            raise RuntimeError(f"Authenticated dashboard returned HTTP {response.status}")


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def ssh(config: dict[str, str], command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-i",
            config["ssh_key"],
            "-o",
            "IdentitiesOnly=yes",
            f"{config['remote_user']}@{config['remote_host']}",
            command,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def run_command(cmd: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    completed = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return {
        "cmd": " ".join(cmd),
        "cwd": display_path(cwd),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip()[-1000:],
        "stderr": completed.stderr.strip()[-1000:],
    }


def display_path(path: Path) -> str:
    return str(path)


def print_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
        return
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
