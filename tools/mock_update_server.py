# mock_update_server.py
# Local HTTP server that mimics the GitHub releases API for testing the
# Elastic Clothing Fit auto-updater without touching real release history.
#
# Usage:
#   python tools/mock_update_server.py
#
# The server serves:
#   GET /repos/VRC-Staples/Elastic-Clothing-Fit/releases/latest  -> stable JSON
#   GET /repos/VRC-Staples/Elastic-Clothing-Fit/releases/tags/nightly -> nightly JSON
#   GET /download/<filename>  -> streams the selected zip file

import datetime
import http.server
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        """Route access log to the GUI queue instead of stderr."""
        self.server._log(fmt % args)

    def do_GET(self):
        if self.path == '/repos/VRC-Staples/Elastic-Clothing-Fit/releases/latest':
            self._send_release_json(nightly=False)
        elif self.path == '/repos/VRC-Staples/Elastic-Clothing-Fit/releases/tags/nightly':
            self._send_release_json(nightly=True)
        elif self.path.startswith('/download/'):
            self._send_zip()
        else:
            self.send_response(404)
            self.end_headers()

    def _send_release_json(self, nightly):
        cfg = self.server._config()
        version  = cfg['version']
        notes    = cfg['notes']
        port     = cfg['port']
        zip_path = cfg['zip_path']

        if not zip_path:
            self.send_response(503)
            self.end_headers()
            return

        filename = os.path.basename(zip_path)

        if nightly:
            ts       = datetime.datetime.now().strftime('%Y%m%d%H%M')
            tag_name = 'nightly'
            asset_name = f"ElasticClothingFit-v{version}-nightly-{ts}.zip"
        else:
            tag_name   = f"v{version}"
            asset_name = f"ElasticClothingFit-v{version}.zip"

        # Use the actual uploaded filename so the download route resolves it.
        # We serve it under /download/<filename> regardless of asset_name.
        download_url = f"http://localhost:{port}/download/{filename}"

        payload = {
            "tag_name": tag_name,
            "body":     notes,
            "assets": [
                {
                    "name":                 asset_name,
                    "browser_download_url": download_url,
                }
            ],
        }

        body = json.dumps(payload).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_zip(self):
        cfg      = self.server._config()
        zip_path = cfg['zip_path']

        if not zip_path or not os.path.isfile(zip_path):
            self.send_response(404)
            self.end_headers()
            return

        size = os.path.getsize(zip_path)
        self.send_response(200)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Length', str(size))
        self.end_headers()
        with open(zip_path, 'rb') as fh:
            self.wfile.write(fh.read())


# ---------------------------------------------------------------------------
# Server wrapper
# ---------------------------------------------------------------------------

class _MockServer(http.server.HTTPServer):
    """HTTPServer subclass that carries shared config and a log queue."""

    def __init__(self, port, config_fn, log_fn):
        super().__init__(('localhost', port), _Handler)
        self._config  = config_fn
        self._log     = log_fn


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class MockServerGUI:

    def __init__(self, root):
        self._root   = root
        self._server = None
        self._thread = None
        self._logq   = queue.Queue()

        root.title("Elastic Fit - Mock Update Server")
        root.resizable(False, False)

        pad = dict(padx=6, pady=4)

        # -- zip file --
        row = tk.Frame(root)
        row.pack(fill='x', **pad)
        tk.Label(row, text="Zip file:", width=14, anchor='w').pack(side='left')
        self._zip_var = tk.StringVar()
        tk.Entry(row, textvariable=self._zip_var, width=42).pack(side='left', padx=(0, 4))
        tk.Button(row, text="Browse", command=self._browse).pack(side='left')

        # -- version --
        row = tk.Frame(root)
        row.pack(fill='x', **pad)
        tk.Label(row, text="Version:", width=14, anchor='w').pack(side='left')
        self._ver_var = tk.StringVar(value="1.0.6")
        tk.Entry(row, textvariable=self._ver_var, width=12).pack(side='left')

        # -- channel --
        row = tk.Frame(root)
        row.pack(fill='x', **pad)
        tk.Label(row, text="Channel:", width=14, anchor='w').pack(side='left')
        self._channel_var = tk.StringVar(value="stable")
        tk.Radiobutton(row, text="Stable",  variable=self._channel_var, value="stable").pack(side='left')
        tk.Radiobutton(row, text="Nightly", variable=self._channel_var, value="nightly").pack(side='left')

        # -- port --
        row = tk.Frame(root)
        row.pack(fill='x', **pad)
        tk.Label(row, text="Port:", width=14, anchor='w').pack(side='left')
        self._port_var = tk.StringVar(value="8198")
        tk.Entry(row, textvariable=self._port_var, width=8).pack(side='left')

        # -- release notes --
        row = tk.Frame(root)
        row.pack(fill='x', **pad)
        tk.Label(row, text="Release notes:", width=14, anchor='nw').pack(side='left')
        self._notes_text = tk.Text(row, width=42, height=4, wrap='word')
        self._notes_text.pack(side='left')

        # -- start/stop --
        self._btn = tk.Button(root, text="Start Server", command=self._toggle, width=14)
        self._btn.pack(**pad)

        # -- log --
        tk.Label(root, text="Request log:").pack(anchor='w', padx=6)
        log_frame = tk.Frame(root)
        log_frame.pack(fill='both', expand=True, padx=6, pady=(0, 6))
        self._log_box = tk.Text(log_frame, height=10, width=60, state='disabled', wrap='none')
        scrollbar = tk.Scrollbar(log_frame, command=self._log_box.yview)
        self._log_box.configure(yscrollcommand=scrollbar.set)
        self._log_box.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # poll the log queue
        root.after(200, self._poll_log)

    # -- config accessor called from handler thread --

    def _get_config(self):
        return {
            'zip_path': self._zip_var.get().strip(),
            'version':  self._ver_var.get().strip(),
            'channel':  self._channel_var.get(),
            'notes':    self._notes_text.get('1.0', 'end').strip(),
            'port':     int(self._port_var.get().strip()),
        }

    # -- callbacks --

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select zip file",
            filetypes=[("Zip files", "*.zip"), ("All files", "*.*")],
        )
        if path:
            self._zip_var.set(path)

    def _toggle(self):
        if self._server is None:
            self._start()
        else:
            self._stop()

    def _start(self):
        zip_path = self._zip_var.get().strip()
        if not zip_path:
            self._append_log("ERROR: No zip file selected.")
            return
        if not os.path.isfile(zip_path):
            self._append_log(f"ERROR: File not found: {zip_path}")
            return

        try:
            port = int(self._port_var.get().strip())
        except ValueError:
            self._append_log("ERROR: Invalid port number.")
            return

        try:
            self._server = _MockServer(port, self._get_config, self._logq.put)
        except OSError as exc:
            self._append_log(f"ERROR: Could not bind port {port}: {exc}")
            return

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        self._btn.config(text="Stop Server")
        self._append_log(f"Server started on http://localhost:{port}")

    def _stop(self):
        if self._server:
            # shutdown() blocks until serve_forever() returns; run it off-thread.
            threading.Thread(target=self._server.shutdown, daemon=True).start()
            self._server = None
            self._thread = None
        self._btn.config(text="Start Server")
        self._append_log("Server stopped.")

    # -- logging --

    def _append_log(self, msg):
        self._log_box.config(state='normal')
        self._log_box.insert('end', msg + '\n')
        self._log_box.see('end')
        self._log_box.config(state='disabled')

    def _poll_log(self):
        while True:
            try:
                msg = self._logq.get_nowait()
                self._append_log(msg)
            except queue.Empty:
                break
        self._root.after(200, self._poll_log)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    root = tk.Tk()
    MockServerGUI(root)
    root.mainloop()
