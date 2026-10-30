#!/usr/bin/env python3
"""Read-only GitLab onboarding inventory. Python standard library only."""

import argparse
import json
import os
import re
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class ProbeError(Exception):
    pass


def parse_project(value, api_base=None, allow_http=False):
    """Normalize web/clone addresses. Custom Web roots require explicit API base."""
    value = value.strip()
    if not value or any(ord(c) < 32 for c in value):
        raise ProbeError("Invalid project address.")
    scp = re.fullmatch(r"[^/@\s]+@([^/:\s]+):(.+)", value)
    if scp:
        transport, host, path = "ssh", scp[1], scp[2]
        origin = "https://" + host
    else:
        parsed = urlsplit(value)
        if parsed.scheme not in (("http", "https", "ssh") if allow_http else ("https", "ssh")) or not parsed.hostname:
            raise ProbeError("Use HTTPS or SSH; an explicitly chosen HTTP instance requires --allow-http.")
        if parsed.query or parsed.fragment or parsed.password:
            raise ProbeError("Remove query strings, fragments and embedded credentials.")
        if parsed.scheme in ("http", "https") and parsed.username:
            raise ProbeError("Credentials must not be embedded in the project URL.")
        transport, host, path = parsed.scheme, parsed.hostname, parsed.path
        # SSH and Web ports are unrelated. Use --api-base for a custom Web port.
        authority = "[" + host + "]" if ":" in host else host
        if transport in ("http", "https") and parsed.port:
            authority += ":" + str(parsed.port)
        origin = (transport if transport in ("http", "https") else "https") + "://" + authority
    inferred = api_base is None
    api_base = (api_base or origin + "/api/v4").rstrip("/")
    api = urlsplit(api_base)
    if (api.scheme not in (("https", "http") if allow_http else ("https",)) or not api.hostname or api.username or api.password
            or api.query or api.fragment or not api.path.endswith("/api/v4")):
        raise ProbeError("API base must end in /api/v4 without credentials; HTTP requires --allow-http.")
    if api.hostname.lower() != host.lower():
        raise ProbeError("API host must match the project host.")
    web_prefix = api.path[:-len("/api/v4")].strip("/")
    path = unquote(path).strip("/").split("/-/", 1)[0]
    if web_prefix and transport in ("http", "https"):
        if path.startswith(web_prefix + "/"):
            path = path[len(web_prefix) + 1:]
        else:
            raise ProbeError("Project URL does not match the GitLab Web subpath.")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if (len(parts) < 2 or any(p in ("", ".", "..") for p in parts)
            or any(not re.fullmatch(r"[\w.-]+", p) for p in parts)):
        raise ProbeError("Invalid namespace/project path; provide a project or clone URL.")
    web_root = api_base[:-len("/api/v4")]
    return {
        "api_base": api_base,
        "project_path": path,
        "project_url": web_root + "/" + quote(path, safe="/"),
        "api_base_inferred": inferred,
        "transport": transport,
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward private tokens, even to an unexpected same-host login page.
        raise ProbeError("API redirect refused; verify the canonical API base URL.")


class Client:
    def __init__(self, base, token=None, ca_file=None, timeout=20):
        self.base = base
        self.token = token
        self.timeout = timeout
        context = ssl.create_default_context(cafile=ca_file)
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=context))

    def get(self, route, params=None):
        url = self.base + route
        if params:
            url += "?" + urlencode(params)
        headers = {"Accept": "application/json", "User-Agent": "gitlab-delivery-guide-probe/1"}
        if self.token:
            headers["PRIVATE-TOKEN"] = self.token
        try:
            with self.opener.open(Request(url, headers=headers, method="GET"), timeout=self.timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ProbeError("API response too large.")
                try:
                    return json.loads(raw), response.headers
                except (ValueError, UnicodeDecodeError):
                    raise ProbeError("Expected JSON from GitLab API; verify the API base.") from None
        except HTTPError as exc:
            # Do not dump response bodies, request headers or credential values.
            raise ProbeError("GitLab API HTTP " + str(exc.code)) from None
        except (URLError, TimeoutError, OSError):
            raise ProbeError("GitLab network/TLS request failed; check access and CA trust.") from None

    def list(self, route, params=None, max_pages=10):
        items = []
        for page in range(1, max_pages + 1):
            data, headers = self.get(route, dict(params or {}, per_page=100, page=page))
            if not isinstance(data, list):
                raise ProbeError("Expected a GitLab list response.")
            items.extend(data)
            next_page = headers.get("X-Next-Page")
            if next_page == "" or (next_page is None and len(data) < 100):
                return {"items": items, "truncated": False}
        return {"items": items, "truncated": True}


def select(data, keys):
    return {k: data[k] for k in keys if k in data}


def probe(client, target, ref=None):
    project, _ = client.get("/projects/" + quote(target["project_path"], safe=""))
    if not isinstance(project, dict) or not isinstance(project.get("id"), int):
        raise ProbeError("Project API returned no valid project ID.")
    root = "/projects/" + str(project["id"])
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read-only-inventory",
        "target": target,
        "project": select(project, ("id", "path_with_namespace", "default_branch", "web_url",
                                    "ci_config_path", "empty_repo", "archived")),
        "ref": ref or project.get("default_branch"),
        "ref_source": "user" if ref else "default-branch-for-inspection-only",
        "observations": {},
    }
    observations = result["observations"]

    def optional(name, action):
        try:
            observations[name] = {"status": "ok", "data": action()}
        except ProbeError as exc:
            observations[name] = {"status": "unknown", "reason": str(exc)}

    optional("version", lambda: select(client.get("/version")[0], ("version", "revision")))
    optional("languages", lambda: client.get(root + "/languages")[0])
    if result["ref"]:
        branch, _ = client.get(root + "/repository/branches/" + quote(result["ref"], safe=""))
        result["commit_sha"] = branch["commit"]["id"]
        result["branch_protected"] = branch.get("protected")
        # Pin tree inventory to the inspected commit rather than a moving branch.
        optional("root_tree", lambda: client.list(root + "/repository/tree", {"ref": result["commit_sha"]}))
    else:
        result["commit_sha"] = None
        observations["root_tree"] = {"status": "unknown", "reason": "No branch in empty repository."}

    def runners():
        page = client.list(root + "/runners")
        page["items"] = [select(r, ("id", "description", "runner_type", "status", "paused", "online"))
                         for r in page["items"]]
        page["tags_require_detail_lookup"] = True
        return page

    def pipelines():
        params = {"per_page": 5}
        if result["ref"]:
            params["ref"] = result["ref"]
        rows, _ = client.get(root + "/pipelines", params)
        return [select(p, ("id", "sha", "ref", "status", "web_url")) for p in rows]

    optional("runners", runners)
    optional("recent_pipelines", pipelines)
    result["limitations"] = [
        "Inventory is not a deployment or acceptance result.",
        "No CI variable values were requested; deployment target and business assertions require repository investigation.",
        "Runner visibility/online status does not prove tags, executor, interactive session or target hostname.",
    ]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_url")
    parser.add_argument("--api-base", help="Canonical HTTPS GitLab API root, ending /api/v4")
    parser.add_argument("--ref", help="Branch to inspect; default branch is not deployment authorization")
    parser.add_argument("--token-env", default="GITLAB_TOKEN", help="Environment variable name, never the token value")
    parser.add_argument("--ca-file", help="Trusted CA bundle PEM file")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--parse-only", action="store_true", help="Normalize URL without any network requests")
    parser.add_argument("--allow-http", action="store_true", help="Use only when the user explicitly selected an HTTP GitLab instance; never bypass HTTPS validation")
    parser.add_argument("--output", help="Write JSON to a new local file; refuses to overwrite")
    args = parser.parse_args(argv)
    try:
        target = parse_project(args.project_url, args.api_base, args.allow_http)
        if not 1 <= args.timeout <= 120:
            raise ProbeError("Timeout must be between 1 and 120 seconds.")
        if args.parse_only:
            result = target
        else:
            client = Client(target["api_base"], os.environ.get(args.token_env), args.ca_file, args.timeout)
            result = probe(client, target, args.ref)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with Path(args.output).open("x", encoding="utf-8") as stream:
                stream.write(payload)
            print("Read-only inventory written to requested local file.")
        else:
            print(payload, end="")
        return 0
    except (ProbeError, ValueError, KeyError, TypeError, OSError) as exc:
        # Unexpected shape errors must also avoid dumping raw API data.
        message = str(exc) if isinstance(exc, ProbeError) else "Invalid input, API response or output file; verify configuration."
        print("Probe failed: " + message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
