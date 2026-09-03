#!/usr/bin/env python3
"""讯飞发版上传 harness：把渠道 APK 通过 loopback HTTP 暴露给已登录的控制台页面。

浏览器工具直传 44MB APK 不可行（claude-in-chrome file_upload 限 10MB，
chrome-devtools 拉起的是无登录态实例），原生文件选择器又不能自动化。
本脚本让控制台页面自己 fetch 到 APK 字节，再由页面 JS 注入站点自身的
上传控件，走的仍是站点原本的上传逻辑。

用法：
    python3 cors_upload_server.py <apk-path> [port]

只绑 127.0.0.1，只读地 serve APK 所在目录，用完立刻 Ctrl-C / pkill。
"""

import functools
import http.server
import os
import sys


class CORSHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        # Chrome Private Network Access 预检需要这一条
        self.send_header("Access-Control-Allow-Private-Network", "true")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("[serve] " + fmt % args + "\n")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    apk = os.path.abspath(sys.argv[1])
    if not os.path.isfile(apk):
        sys.exit(f"APK not found: {apk}")

    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    directory = os.path.dirname(apk)

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", port),
        functools.partial(CORSHandler, directory=directory),
    )
    print(f"serving {directory} on 127.0.0.1:{port}", flush=True)
    print(f"url  http://127.0.0.1:{port}/{os.path.basename(apk)}", flush=True)
    print(f"size {os.path.getsize(apk)} bytes", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
