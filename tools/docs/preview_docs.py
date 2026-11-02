#!/usr/bin/env python3
"""One-port live preview of OpenCUTE's main/trace, SDK and design documentation.

Run with ordinary Python 3. The builder interpreter is selected separately, so
VS Code's default Python need not have MkDocs installed. No dependencies are
installed automatically. Generated sites live in a temporary directory.
"""
import argparse
import io
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
WATCH = [ROOT / p for p in (
    'doc/docs', 'trace/docs', 'doc/sdk-doc/docs', 'doc/design-doc/docs',
    'doc/mkdocs.yml', 'doc/sdk-doc/mkdocs.yml', 'doc/design-doc/mkdocs.yml',
    'tools/docs/build_docs.py', 'tools/docs/check_links.py',
)]
LIVE_SCRIPT = r"""(() => {
  const initial = document.currentScript.dataset.revision;
  let busy = false;
  function banner(message) {
    let node = document.getElementById('opencute-preview-status');
    if (!node) {
      node = document.createElement('div'); node.id = 'opencute-preview-status';
      node.style.cssText = 'position:fixed;bottom:12px;right:12px;max-width:85vw;max-height:35vh;overflow:auto;z-index:9999;padding:10px 16px;background:#263238;color:white;border-radius:6px;white-space:pre-wrap;font:14px sans-serif;box-shadow:0 2px 10px #0006';
      document.body.appendChild(node);
    }
    node.textContent = message; node.hidden = !message;
  }
  const key = 'opencute-preview-scroll:' + location.pathname;
  try {
    const saved = sessionStorage.getItem(key);
    if (saved !== null) { sessionStorage.removeItem(key); requestAnimationFrame(() => scrollTo(0, Number(saved))); }
  } catch (_) {}
  async function poll() {
    if (busy) return; busy = true;
    try {
      const response = await fetch('/__opencute_preview/status', {cache: 'no-store'});
      if (!response.ok) throw new Error('preview unavailable');
      const status = await response.json();
      if (status.session + ':' + status.revision !== initial) {
        try { sessionStorage.setItem(key, String(scrollY)); } catch (_) {}
        location.reload(); return;
      }
      banner(status.state === 'error' ? '构建失败，仍显示上次成功版本。\n' + status.error
             : status.state === 'building' ? '正在更新文档…' : '');
    } catch (_) { banner('预览服务已停止或连接断开。重新运行脚本后会自动恢复。'); }
    finally { busy = false; }
  }
  setInterval(poll, 1000); poll();
})();
"""


def builder_python(explicit):
    """Prefer the caller's environment; reuse this server's existing doc env."""
    requested = explicit or os.environ.get('CUTE_DOCS_PYTHON')
    candidates = [requested] if requested else [
        sys.executable,
        ROOT / '.venv-docs/bin/python',
        ROOT / '.venv/bin/python',
        *sorted((ROOT.parent / 'workspace').glob('cute-model-migration-*/tools/docs/bin/python'), reverse=True),
    ]
    seen = set()
    for candidate in candidates:
        executable = shutil.which(str(candidate))
        if not executable or executable in seen:
            continue
        seen.add(executable)
        try:
            result = subprocess.run(
                [executable, '-c', 'import mkdocs, material, mermaid2, yaml'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            if result.returncode == 0:
                return executable
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError(
        '找不到含文档依赖的 Python。激活文档环境并安装 doc/requirements.txt，'
        '再用 --python /path/to/env/bin/python 指定解释器。')


def fingerprint():
    files = []
    for target in WATCH:
        if target.is_dir():
            for directory, dirs, names in os.walk(target):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
                files.extend(Path(directory) / name for name in names
                             if not name.startswith('.') and not name.endswith(('~', '.swp', '.pyc')))
        else:
            files.append(target)
    result = []
    for path in sorted(files):
        try:
            stat = path.stat()
            result.append((str(path), stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            result.append((str(path), None, None))
    return tuple(result)


class PreviewState:
    def __init__(self, empty):
        self.lock = threading.Lock()
        self.directory = empty
        self.session = str(time.time_ns())
        self.revision = 0
        self.state = 'building'
        self.error = ''

    def read(self):
        with self.lock:
            return self.directory, dict(session=self.session, revision=self.revision, state=self.state, error=self.error)

    def update(self, state, error='', directory=None):
        with self.lock:
            self.state, self.error = state, error
            if directory is not None:
                self.directory = directory
                self.revision += 1


def handler_for(state):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            self.root, self.status = state.read()
            super().__init__(*args, directory=str(self.root), **kwargs)

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()

        def log_message(self, fmt, *args):
            pass

        def content(self, payload, mime, code=200):
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            return io.BytesIO(payload)

        def send_head(self):
            path = unquote(urlsplit(self.path).path)
            if path == '/__opencute_preview/status':
                return self.content(json.dumps(state.read()[1], ensure_ascii=False).encode(), 'application/json; charset=utf-8')
            if path == '/__opencute_preview/live.js':
                return self.content(LIVE_SCRIPT.encode(), 'application/javascript; charset=utf-8')
            target = Path(self.translate_path(self.path)).resolve()
            # Only serve generated site files, including when a source asset is a symlink.
            if self.root.resolve() not in target.parents and target != self.root.resolve():
                self.send_error(403)
                return None
            if target.is_dir():
                if not path.endswith('/'):
                    return super().send_head()
                target /= 'index.html'
            script = ('<script data-revision="' + self.status['session'] + ':' + str(self.status['revision'])
                      + '" src="/__opencute_preview/live.js"></script>')
            if target.is_file() and target.suffix == '.html':
                html = target.read_text()
                html = html.replace('</body>', script + '</body>') if '</body>' in html else html + script
                return self.content(html.encode(), 'text/html; charset=utf-8')
            if self.status['revision'] == 0:
                return self.content(('<!doctype html><meta charset="utf-8"><body><h1>OpenCUTE 文档预览</h1>'
                                     '<p>正在构建主文档、SDK 和设计站点，请稍候…</p>' + script + '</body>').encode(),
                                    'text/html; charset=utf-8')
            return super().send_head()

        def list_directory(self, path):
            self.send_error(404)
            return None
    return Handler


def terminate(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def watch(state, python, work, url, interval):
    attempted = None
    generation = 0
    successful = []
    process = None
    try:
        while True:
            changed = fingerprint()
            if changed == attempted:
                time.sleep(interval)
                continue
            time.sleep(0.35)  # Coalesce atomic editor saves and small edit bursts.
            if fingerprint() != changed:
                continue
            attempted = changed
            generation += 1
            destination = work / ('site-' + str(generation))
            log = work / 'latest-build.log'
            state.update('building')
            print('DOCS_BUILD: 正在构建三个站点…', flush=True)
            command = [python, str(ROOT / 'tools/docs/build_docs.py'), '--out', str(destination), '--site-url', url]
            with log.open('wb') as output:
                process = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=output, start_new_session=True)
                rc = process.wait()
            process = None
            if rc:
                detail = log.read_text(errors='replace')[-2000:]
                logs = work / (destination.name + '-logs')
                for name in ('main', 'sdk', 'design', 'links'):
                    path = logs / (name + '.log')
                    if path.exists():
                        tail = path.read_text(errors='replace')
                        if re.search(r'(?m)^(WARNING|ERROR|Traceback)|missing (anchor|file)', tail):
                            detail += '\n' + name + ':\n' + tail[-2000:]
                state.update('error', re.sub(r'\x1b\[[0-9;]*m', '', detail[-6000:]) + '\n日志目录：' + str(logs))
                print('DOCS_BUILD_FAILED: 修改后会重试；保留上次成功版本。\n' + detail, flush=True)
                shutil.rmtree(destination, ignore_errors=True)
                continue
            if fingerprint() != attempted:
                print('DOCS_BUILD: 构建期间检测到新修改，继续更新…', flush=True)
                shutil.rmtree(destination, ignore_errors=True)
                continue
            state.update('ready', directory=destination)
            successful.append(destination)
            if len(successful) > 2:
                shutil.rmtree(successful.pop(0), ignore_errors=True)
            print('DOCS_PREVIEW_READY: ' + url + '（保存源文档后自动刷新）', flush=True)
    finally:
        terminate(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8010)
    parser.add_argument('--python', help='含 doc/requirements.txt 依赖的 Python；也可设置 CUTE_DOCS_PYTHON')
    parser.add_argument('--interval', type=float, default=0.5, help='源文件检查间隔（秒）')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 0.1 <= args.interval <= 60:
        parser.error('port 须为 1–65535，interval 须为 0.1–60 秒')
    try:
        python = builder_python(args.python)
    except RuntimeError as error:
        parser.exit(1, str(error) + '\n')
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    with tempfile.TemporaryDirectory(prefix='opencute-doc-preview-') as directory:
        work = Path(directory)
        empty = work / 'empty'
        empty.mkdir()
        state = PreviewState(empty)
        try:
            server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(state))
        except OSError as error:
            parser.exit(1, f'端口 {args.port} 无法监听：{error}。可用 --port 换端口。\n')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{args.port}/'
        print('DOCS_PREVIEW_STARTING: ' + url, flush=True)
        print(f'构建解释器：{python}\n临时输出：{work}\n主站 / · SDK /sdk/ · 硬件 /design/\n按 Ctrl+C 停止。', flush=True)
        try:
            watch(state, python, work, url, args.interval)
        except KeyboardInterrupt:
            print('\n文档预览已停止。', flush=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
