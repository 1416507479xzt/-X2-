"""Read-only local dashboard for confirmed dining feedback."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from x2_agent.dining_feedback import load_feedback, render_dashboard


def main():
    parser = argparse.ArgumentParser(description="社区食堂反馈表（仅本机访问）")
    parser.add_argument("--records", help="反馈JSONL路径；默认data/dining_feedback.jsonl")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            try:
                page = render_dashboard(load_feedback(args.records)).encode("utf-8")
            except (OSError, ValueError):
                self.send_error(503, "反馈数据暂不可读")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"本地反馈表: http://127.0.0.1:{args.port}/")
        server.serve_forever()


if __name__ == "__main__":
    main()
