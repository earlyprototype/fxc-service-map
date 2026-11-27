import http.client
import json
import os
import runpy
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import HTTPRedirectHandler


class ChatServerTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().with_name("chat_server.py")
        temporary = tempfile.TemporaryDirectory(dir=source.parent)
        self.addCleanup(temporary.cleanup)
        self.checkout = Path(temporary.name) / "checkout"
        self.home = Path(temporary.name) / "home"
        data = self.checkout / "_data"
        data.mkdir(parents=True)
        self.script = self.checkout / source.name
        shutil.copyfile(source, self.script)
        (self.checkout / "index.html").write_bytes(b"map preview")
        self.entities = json.dumps({
            "categories": [{"id": "c", "label": "Category"}],
            "pillars": [{"id": "p", "label": "Pillar"}],
            "partners": [{"id": "lab", "label": "Lab", "contact": "Desk"}],
            "services": [{
                "id": "sample", "label": "Sample service", "partner": "lab",
                "category": "c", "pillar": "p", "desc": "Sample summary",
                "full": "Sample focus detail", "url": "https://example.invalid/service",
            }],
        }).encode("utf-8")
        (data / "entities.json").write_bytes(self.entities)
        self.config = self.home / ".config" / "fxc-service-map" / "chat_config.json"
        self.config.parent.mkdir(parents=True)
        home = patch.object(Path, "home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)
        network = patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected provider request"))
        self.urlopen = network.start()
        self.addCleanup(network.stop)
        self.app = runpy.run_path(str(self.script))

    def start_http(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.app["Handler"])
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.address = server.server_address

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.address, timeout=3)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def chat(self, focus=None):
        payload = {"messages": [{"role": "user", "text": "Find a service"}]}
        if focus is not None:
            payload["focus"] = focus
        status, reply = self.request("POST", "/api/chat", json.dumps(payload))
        self.assertEqual(status, 200)
        return json.loads(reply)["reply"]

    def run_main(self):
        with patch("http.server.ThreadingHTTPServer") as server, patch("builtins.print"):
            self.app = runpy.run_path(str(self.script), run_name="__main__")
        self.assertEqual(server.call_args.args[0], ("127.0.0.1", 8020))
        server.return_value.serve_forever.assert_called_once_with()

    def test_default_listener(self):
        self.run_main()

    def assert_map_runs_without_chat(self):
        self.run_main()
        self.start_http()
        self.assertEqual(self.request("GET", "/"), (200, b"map preview"))
        self.assertIn("isn't configured", self.chat())

    def test_startup_without_a_home_directory(self):
        with patch.object(Path, "home", side_effect=RuntimeError("No home directory")):
            self.assert_map_runs_without_chat()

    def test_startup_when_config_lookup_is_denied(self):
        self.config.write_text('{"api_key":"dummy"}')
        resolve = Path.resolve

        def resolve_path(path, *args, **kwargs):
            if path == self.config:
                raise PermissionError("Config lookup denied")
            return resolve(path, *args, **kwargs)

        with patch.object(Path, "resolve", resolve_path):
            self.assert_map_runs_without_chat()

    def test_public_map_routes(self):
        self.start_http()
        for path, expected in [
            ("/", b"map preview"),
            ("/index.html", b"map preview"),
            ("/_data/entities.json?v=1", self.entities),
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path), (200, expected))
                self.assertEqual(self.request("HEAD", path), (200, b""))

    def test_conditional_map_request(self):
        os.utime(self.checkout / "index.html", (1704067200, 1704067200))
        self.start_http()
        headers = {"If-Modified-Since": "Mon, 01 Jan 2024 00:00:00 GMT"}
        self.assertEqual(self.request("GET", "/", headers=headers), (304, b""))
        headers["If-Modified-Since"] = "Sun, 31 Dec 2023 23:59:59 GMT"
        self.assertEqual(self.request("GET", "/", headers=headers), (200, b"map preview"))

    def test_get_keeps_file_identity_during_replacement(self):
        index = self.checkout / "index.html"
        updated = self.checkout / "updated.html"
        updated.write_bytes(b"updated map")
        handler = self.app["Handler"]

        with HTTPServer(("127.0.0.1", 0), handler) as server, ThreadPoolExecutor(2) as workers:
            server.timeout = 3
            self.address = server.server_address

            def get_index():
                reply = workers.submit(self.request, "GET", "/")
                server.handle_request()
                return reply.result(timeout=3)

            # Pause header preparation while another thread publishes a new index.
            def content_type(path):
                try:
                    workers.submit(updated.replace, index).result(timeout=3)
                except PermissionError as exc:
                    # Windows can keep the verified file locked until GET finishes.
                    if getattr(exc, "winerror", None) not in (5, 32):
                        raise
                return "text/html"

            with patch.object(handler, "guess_type", side_effect=content_type) as guess:
                self.assertEqual(get_index(), (200, b"map preview"))
                guess.assert_called_once()

            if updated.exists():
                updated.replace(index)
            self.assertEqual(get_index(), (200, b"updated map"))

    def test_private_files_and_directories_are_unavailable(self):
        (self.checkout / "chat_config.json").write_text('{"api_key":"dummy"}')
        (self.checkout / "_data" / "notes.txt").write_text("local notes")
        self.start_http()
        for path in ["/chat_config.json", "/chat_server.py", "/_data/notes.txt", "/_data/"]:
            for method in ["GET", "HEAD"]:
                with self.subTest(method=method, path=path):
                    self.assertEqual(self.request(method, path)[0], 404)

    def test_chat_uses_only_the_private_config(self):
        (self.checkout / "chat_config.json").write_text('{"api_key":"dummy-old"}')
        self.start_http()
        provider = Mock(return_value="offline reply")
        with patch.dict(self.app["PROVIDERS"], {"gemini": provider}):
            self.assertIn("isn't configured", self.chat())
            provider.assert_not_called()
            self.config.write_text('{"provider":"gemini","api_key":"dummy-private"}')
            self.assertEqual(self.chat(), "offline reply")
            self.assertEqual(provider.call_args.args[0]["api_key"], "dummy-private")

    def test_chat_rejects_a_home_config_inside_the_map_directory(self):
        config = self.checkout / self.config.relative_to(self.home)
        config.parent.mkdir(parents=True)
        config.write_text('{"api_key":"dummy"}')
        with patch.object(Path, "home", return_value=self.checkout):
            self.assert_map_runs_without_chat()
        self.urlopen.assert_not_called()

    def test_provider_error_keeps_key_out_of_reply(self):
        self.config.write_text('{"provider":"gemini","api_key":"dummy-private"}')
        self.start_http()
        self.urlopen.side_effect = ValueError("dummy-private")
        reply = self.chat()
        self.assertNotIn("dummy-private", reply)
        self.assertIn("provider", reply)
        request = self.urlopen.call_args.args[0]
        self.assertNotIn("dummy-private", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "dummy-private")

    def test_provider_keys_stay_on_the_original_request(self):
        self.urlopen.side_effect = OSError("Offline")
        for provider, header in (("gemini", "X-goog-api-key"), ("anthropic", "X-api-key")):
            with self.subTest(provider=provider):
                with self.assertRaises(OSError):
                    self.app["PROVIDERS"][provider]({"api_key": "dummy"}, "Sample prompt", [])
                original = self.urlopen.call_args.args[0]
                self.assertEqual(original.get_header(header), "dummy")
                redirected = HTTPRedirectHandler().redirect_request(
                    original, None, 302, "Found", {}, "https://example.invalid/redirect",
                )
                self.assertFalse(redirected.has_header(header))

    def test_directory_at_map_filename_is_unavailable(self):
        index = self.checkout / "index.html"
        index.unlink()
        index.mkdir()
        self.start_http()
        self.assertEqual(self.request("GET", "/")[0], 404)

    def test_multiply_linked_asset_is_unavailable(self):
        (self.home / "map-copy.html").hardlink_to(self.checkout / "index.html")
        self.start_http()
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                self.assertEqual(self.request(method, "/index.html")[0], 404)

    def link_catalogue_directory(self):
        data = self.checkout / "_data"
        target = self.home / "sample-catalogue"
        data.rename(target)
        if os.name == "nt":
            # A directory junction exercises the link check without symlink privileges.
            import _winapi
            _winapi.CreateJunction(str(target), str(data))
        else:
            data.symlink_to(target, target_is_directory=True)

    def test_catalogue_route_rejects_a_linked_directory(self):
        self.link_catalogue_directory()
        self.start_http()
        self.assertEqual(self.request("GET", "/_data/entities.json")[0], 404)

    def test_chat_rejects_linked_catalogue_at_startup(self):
        self.link_catalogue_directory()
        self.config.write_text('{"api_key":"dummy"}')
        self.run_main()
        self.start_http()
        self.assertEqual(self.request("GET", "/"), (200, b"map preview"))
        provider = Mock(return_value="offline reply")
        with patch.dict(self.app["PROVIDERS"], {"gemini": provider}):
            self.assertIn("catalogue", self.chat())
            provider.assert_not_called()

    def test_chat_rejects_linked_catalogue_for_focus(self):
        self.config.write_text('{"api_key":"dummy"}')
        self.start_http()
        provider = Mock(return_value="offline reply")
        with patch.dict(self.app["PROVIDERS"], {"gemini": provider}):
            self.assertEqual(self.chat(["sample"]), "offline reply")
            prompt = provider.call_args.args[1]
            self.assertIn("Sample summary", prompt)
            self.assertIn("Sample focus detail", prompt)
            self.link_catalogue_directory()
            self.assertIn("catalogue", self.chat(["sample"]))
            provider.assert_called_once()


if __name__ == "__main__":
    unittest.main()
