"""Offline contract checks; never connects to a GitLab server."""

import unittest
from unittest.mock import patch
from urllib.request import Request

from gitlab_probe import Client, NoRedirect, ProbeError, parse_project, probe


class ProbeTests(unittest.TestCase):
    def test_web_subgroup_port_and_page(self):
        target = parse_project("https://code.example.test:8443/team/sub/app/-/tree/feature/x")
        self.assertEqual(target["project_path"], "team/sub/app")
        self.assertEqual(target["api_base"], "https://code.example.test:8443/api/v4")

    def test_ssh_port_is_not_web_port(self):
        target = parse_project("ssh://git@code.example.test:2222/team/app.git")
        self.assertEqual(target["api_base"], "https://code.example.test/api/v4")
        target = parse_project("git@code.example.test:team/app.git", "https://code.example.test:8443/api/v4")
        self.assertEqual(target["project_url"], "https://code.example.test:8443/team/app")

    def test_web_subpath(self):
        target = parse_project("https://code.example.test/gitlab/team/app.git",
                               "https://code.example.test/gitlab/api/v4")
        self.assertEqual(target["project_path"], "team/app")
        self.assertEqual(target["project_url"], "https://code.example.test/gitlab/team/app")

    def test_http_requires_explicit_opt_in_and_preserves_port(self):
        with self.assertRaises(ProbeError):
            parse_project("http://code.example.test:8080/team/app")
        target = parse_project("http://code.example.test:8080/team/app", allow_http=True)
        self.assertEqual(target["api_base"], "http://code.example.test:8080/api/v4")
        self.assertEqual(target["project_url"], "http://code.example.test:8080/team/app")
        with self.assertRaises(ProbeError):
            parse_project("http://token@code.example.test:8080/team/app", allow_http=True)

    def test_ssh_namespace_does_not_lose_web_prefix(self):
        target = parse_project("git@code.example.test:gitlab/team/app.git",
                               "https://code.example.test/gitlab/api/v4")
        self.assertEqual(target["project_path"], "gitlab/team/app")
        self.assertEqual(target["project_url"], "https://code.example.test/gitlab/gitlab/team/app")

    def test_reject_credential_or_unsafe_target(self):
        for url in ("https://secret@code.example.test/team/app", "https://code.example.test/team/app?token=secret",
                    "http://code.example.test/team/app", "https://code.example.test/team/../app",
                    "https://code.example.test/team/%2e%2e/app", "https://code.example.test/team/app#secret"):
            with self.subTest(url=url), self.assertRaises(ProbeError):
                parse_project(url)
        with self.assertRaises(ProbeError):
            parse_project("https://code.example.test/team/app", "https://other.example.test/api/v4")

    def test_redirect_does_not_forward_authentication(self):
        with self.assertRaises(ProbeError):
            NoRedirect().redirect_request(Request("https://code.example.test/api/v4/projects/1",
                                                 headers={"PRIVATE-TOKEN": "sample"}),
                                          None, 302, "Found", {}, "https://other.example.test/")

    def test_probe_pins_sha_and_preserves_unknown_permissions(self):
        calls = []

        class FakeClient:
            def get(self, route, params=None):
                calls.append((route, params))
                if route == "/projects/team%2Fapp":
                    return {"id": 8, "default_branch": "main"}, {}
                if "/repository/branches/" in route:
                    return {"commit": {"id": "a" * 40}, "protected": False}, {}
                if route.endswith("/languages"):
                    return {"Java": 90}, {}
                if route.endswith("/pipelines"):
                    return [{"id": 9, "status": "success", "unexpected": "not copied"}], {}
                raise ProbeError("GitLab API HTTP 403")

            def list(self, route, params=None):
                calls.append((route, params))
                if route.endswith("/runners"):
                    raise ProbeError("GitLab API HTTP 403")
                return {"items": [{"name": "pom.xml"}], "truncated": False}

        result = probe(FakeClient(), parse_project("https://code.example.test/team/app"), "feature/x")
        self.assertEqual(result["ref_source"], "user")
        self.assertEqual(result["commit_sha"], "a" * 40)
        self.assertEqual(result["observations"]["runners"]["status"], "unknown")
        self.assertIn(("/projects/8/repository/tree", {"ref": "a" * 40}), calls)
        self.assertIn(("/projects/8/repository/branches/feature%2Fx", None), calls)
        self.assertFalse(any("variables" in route for route, _ in calls))

    def test_pagination_is_bounded_and_reports_truncation(self):
        client = Client("https://code.example.test/api/v4")
        with patch.object(client, "get", return_value=([{"id": 1}] * 100, {"X-Next-Page": "2"})) as request:
            result = client.list("/projects/8/runners", max_pages=2)
        self.assertEqual(request.call_count, 2)
        self.assertTrue(result["truncated"])

    def test_default_branch_is_inspection_only(self):
        class EmptyClient:
            def get(self, route, params=None):
                if route == "/projects/team%2Fapp":
                    return {"id": 8, "default_branch": None, "empty_repo": True}, {}
                raise ProbeError("GitLab API HTTP 403")

            def list(self, route, params=None):
                return {"items": [], "truncated": False}

        result = probe(EmptyClient(), parse_project("https://code.example.test/team/app"))
        self.assertEqual(result["ref_source"], "default-branch-for-inspection-only")
        self.assertIsNone(result["commit_sha"])
        self.assertEqual(result["observations"]["root_tree"]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
