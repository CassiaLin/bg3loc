"""Exercise real local HTTP; denial is a failure, never a skipped/fake PASS."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen
from urllib.error import URLError


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'bg3loc-synthetic-loopback')

    def log_message(self, *_):
        pass


def main():
    server = None
    thread = None
    try:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with urlopen(f'http://127.0.0.1:{server.server_port}/', timeout=5) as response:
            assert response.read() == b'bg3loc-synthetic-loopback'
        print('Real loopback HTTP: PASS')
        return 0
    except Exception as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        print(f'Real loopback HTTP: FAIL ({type(exc).__name__}, '
              f'WinError={getattr(reason, "winerror", None)})')
        return 1
    finally:
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
            server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
