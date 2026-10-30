"""Loopback-only preview of a built Flutter app with a public API proxy."""
import argparse
import json
import re
import subprocess
import tempfile
from hashlib import sha256
from http.client import HTTPConnection, HTTPSConnection
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5181)
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    parser.add_argument('--media-origin', help='Optional public media origin for a read-only snapshot preview')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'build/web'
    shared_assets = Path(__file__).resolve().parents[2] / 'frontend/public'
    upstream = urlsplit(args.api)
    cache = Path(tempfile.mkdtemp(prefix='signal-flutter-media-'))
    media_pattern = re.compile(r'^/api/public/appeals/wall/[0-9]+/(photos|results)/[a-fA-F0-9-]+$')

    class Preview(SimpleHTTPRequestHandler):
        extensions_map: ClassVar[dict[str, str]] = {**SimpleHTTPRequestHandler.extensions_map, '.wasm': 'application/wasm', '.js': 'application/javascript'}

        def __init__(self, *positional, **keywords):
            super().__init__(*positional, directory=str(root), **keywords)

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'strict-origin')
            super().end_headers()

        def proxy(self):
            length = int(self.headers.get('Content-Length', 0))
            if length > 76 * 1024 * 1024:
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else None
            connection_type = HTTPSConnection if upstream.scheme == 'https' else HTTPConnection
            connection = connection_type(upstream.netloc, timeout=120)
            headers = {key: value for key, value in self.headers.items()
                       if key.lower() in {'content-type', 'x-appeal-request', 'x-capture-token', 'origin'}}
            headers['Host'] = self.headers.get('Host', upstream.netloc)
            try:
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                data = response.read()
                content_type = response.getheader('Content-Type', 'application/octet-stream')
                if args.media_origin and 'application/json' in content_type:
                    # Snapshot APIs can return absolute image URLs. Keep CanvasKit images same-origin.
                    text = data.decode('utf-8').replace(args.media_origin.rstrip('/') + '/api/public/appeals/wall/',
                                                       '/api/public/appeals/wall/')
                    json.loads(text)
                    data = text.encode('utf-8')
                self.send_response(response.status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (OSError, ValueError):
                self.send_error(502, 'Local API unavailable')
            finally:
                connection.close()

        def media(self):
            target = cache / (sha256(self.path.encode()).hexdigest() + '.jpg')
            if not target.is_file():
                result = subprocess.run(['curl', '-fsS', '--max-time', '25',
                    args.media_origin.rstrip('/') + self.path, '-o', str(target)], capture_output=True, check=False)
                if result.returncode:
                    target.unlink(missing_ok=True)
                    self.send_error(502, 'Public photograph unavailable')
                    return
            content = target.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in {'/appeal-detail.css', '/appeal-detail.js'}:
                content = (shared_assets / path[1:]).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/css' if path.endswith('.css') else 'application/javascript')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif args.media_origin and media_pattern.fullmatch(path):
                self.media()
            elif path.startswith('/api/public/appeals') or re.fullmatch(r'/a/[0-9]+(/card[.]jpg)?', path):
                self.proxy()
            else:
                super().do_GET()

        def do_POST(self):
            if urlsplit(self.path).path.startswith('/api/public/appeals'):
                self.proxy()
            else:
                self.send_error(404)

        def log_message(self, *_):
            pass

    print(f'Flutter Signal: http://127.0.0.1:{args.port}/', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Preview).serve_forever()


if __name__ == '__main__':
    main()
