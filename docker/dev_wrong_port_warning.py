#!/usr/bin/env python

"""
Per form-case/kobo-docker#301, we have changed the uWSGI port to 8001. This
provides a helpful message to anyone still trying to use port 8000
"""

import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(503)
        self.end_headers()
        self.wfile.write(
            b'Your development environment is trying to connect to the KoBoCAT '
            b'container on port 8000 instead of 8001. Please change this. See '
            b'https://github.com/form-case/kobo-docker/issues/301 '
            b'for more details.'
        )


server_address = ('', int(sys.argv[1]))
httpd = HTTPServer(server_address, Handler)
httpd.serve_forever()
