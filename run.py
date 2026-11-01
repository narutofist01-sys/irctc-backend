import os
import sys
import traceback
import http.server

# Ensure lib directory and backend directory are first in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_dir = os.path.join(current_dir, "lib")

if os.path.exists(lib_dir) and lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import types
try:
    import app
    backend_pkg = types.ModuleType("backend")
    backend_pkg.app = app
    sys.modules["backend"] = backend_pkg
    sys.modules["backend.app"] = app
except Exception:
    pass

if __name__ == "__main__":
    port_str = os.getenv("X_ZOHO_CATALYST_LISTEN_PORT") or os.getenv("PORT") or "9000"
    port = int(port_str)

    try:
        import uvicorn
        from app.main import app
        print(f"Starting IRCTC AGENT Backend with uvicorn on port {port}...", flush=True)
        uvicorn.run(app, host="0.0.0.0", port=port)
    except Exception as e:
        err_text = (
            f"Startup Error:\n{traceback.format_exc()}\n\n"
            f"Python Version: {sys.version}\n"
            f"Sys Path: {sys.path}\n"
            f"Env Vars: {dict(os.environ)}\n"
        )
        print(err_text, file=sys.stderr, flush=True)

        class DiagnosticHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(err_text.encode("utf-8"))

        server = http.server.HTTPServer(("0.0.0.0", port), DiagnosticHandler)
        print(f"Fallback diagnostic server listening on port {port}...", flush=True)
        server.serve_forever()

