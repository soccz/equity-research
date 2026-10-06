"""Loopback-only UI and bounded local update operations."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import urlparse, unquote
from datetime import date, datetime, timezone
from .data import ROOT
from .pipeline import run, register, observe, load_latest


def serve(port=8766):
    status = {"running": False, "error": None}
    lock = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def json_response(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") in {
                f"127.0.0.1:{port}",
                f"localhost:{port}",
            }

        def do_GET(self):
            if not self.valid_host():
                self.json_response({"error": "Local Host required"}, 403)
                return
            route = urlparse(self.path).path
            if route == "/api/status":
                self.json_response(dict(status))
                return
            if route == "/api/snapshot":
                self.json_response(load_latest())
                return
            path = (ROOT / unquote(route).lstrip("/")).resolve()
            if not path.is_relative_to(ROOT) or any(
                p.startswith(".") for p in path.relative_to(ROOT).parts
            ):
                self.send_error(403)
                return
            if path.is_dir() and not (path / "index.html").is_file():
                self.send_error(404)
                return
            if "If-Modified-Since" in self.headers:
                del self.headers["If-Modified-Since"]
            super().do_GET()

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            super().end_headers()

        def do_POST(self):
            action = urlparse(self.path).path.removeprefix("/api/")
            origin = self.headers.get("Origin")
            if (
                not self.valid_host()
                or action not in {"register", "observe", "refresh"}
                or self.headers.get("X-Research-Action") != action
                or (
                    origin
                    and origin
                    not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
                )
            ):
                self.json_response({"error": "Local same-origin action required"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024:
                    raise ValueError("Small JSON body required")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("JSON object required")
                as_of = body.get("asOf", load_latest()["asOf"])
                if date.fromisoformat(as_of) >= datetime.now(timezone.utc).date():
                    raise ValueError("완료된 과거 일자를 사용하세요")
            except (ValueError, TypeError) as exc:
                self.json_response({"error": str(exc)}, 400)
                return
            if not lock.acquire(blocking=False):
                self.json_response({"error": "다른 갱신 작업이 진행 중입니다"}, 409)
                return
            if action == "refresh":
                status.update(running=True, error=None)

                def job():
                    try:
                        result = run(as_of, online=True)
                        if result["failures"]:
                            raise ValueError(
                                "일부 자료 갱신 실패. 직전 완료본 유지: "
                                + json.dumps(result["failures"], ensure_ascii=False)
                            )
                        observe()
                    except Exception as exc:
                        status["error"] = str(exc)
                    finally:
                        status["running"] = False
                        lock.release()

                threading.Thread(target=job, daemon=True).start()
                self.json_response({"job": True}, 202)
            else:
                try:
                    (register if action == "register" else observe)()
                    self.json_response({"ok": True})
                except Exception as exc:
                    self.json_response({"error": str(exc)}, 500)
                finally:
                    lock.release()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Research workspace: http://127.0.0.1:{port}/app/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
