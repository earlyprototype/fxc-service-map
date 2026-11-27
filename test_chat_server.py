import http.client
import json
import os
import runpy
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch


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
        self.entities = b'{"categories": [], "pillars": [], "partners": [], "services": []}'
        (data / "entities.json").write_bytes(self.entities)
        self.config = self.home / ".config" / "fxc-service-map" / "chat_config.json"
        self.config.parent.mkdir(parents=True)
        home = patch.object(Path, "home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)
        self.app = runpy.run_path(str(self.script))

    def start_http(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.app["Handler"])
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.address = server.server_address

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection(*self.address, timeout=3)
        try:
            connection.request(method, path, body)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def chat(self):
        body = json.dumps({"messages": [{"role": "user", "text": "Find a service"}]})
        status, reply = self.request("POST", "/api/chat", body)
        self.assertEqual(status, 200)
        return json.loads(reply)["reply"]

    def test_default_listener(self):
        with patch("http.server.ThreadingHTTPServer") as server, patch("builtins.print"):
            runpy.run_path(str(self.script), run_name="__main__")
        self.assertEqual(server.call_args.args[0], ("127.0.0.1", 8020))

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

    def test_directory_at_map_filename_is_unavailable(self):
        index = self.checkout / "index.html"
        index.unlink()
        index.mkdir()
        self.start_http()
        self.assertEqual(self.request("GET", "/")[0], 404)

    def test_catalogue_route_rejects_a_linked_directory(self):
        data = self.checkout / "_data"
        (data / "entities.json").unlink()
        data.rmdir()
        (self.home / "entities.json").write_text("private data")
        if os.name == "nt":
            # A directory junction exercises the link check without symlink privileges.
            import _winapi
            _winapi.CreateJunction(str(self.home), str(data))
        else:
            data.symlink_to(self.home, target_is_directory=True)
        self.start_http()
        self.assertEqual(self.request("GET", "/_data/entities.json")[0], 404)


if __name__ == "__main__":
    unittest.main()
