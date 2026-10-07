#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mirror_site.py —— 把静态站点完整镜像到本地（多线程 + 可续传）。

针对 mathartbang 地图站的用法：
    1) 先抓页面和 JSON：
       python mirror_site.py --out site --prefix /deca/ --seeds-file bootstrap.txt
    2) 再从 layers.json 生成图片/瓦片清单，继续抓：
       python gen_urls.py --site site > assets.txt
       python mirror_site.py --out site --prefix /deca/ --seeds-file assets.txt

镜像后的目录结构和网址路径一一对应，所以直接把 <out> 当站点根目录起服务即可。
中断后重新运行会跳过已下载的文件（可续传）。
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import random
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_SEEDS = [
    "https://www.mathartbang.com/deca/hp/index.html",
    "https://www.mathartbang.com/deca/hp/map.html",
    "https://www.mathartbang.com/deca/hp/tool/save.html",
]

TEXT_EXT = {
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".txt",
    ".xml", ".svg", ".geojson", ".csv",
}

ASSET_EXT_RE = re.compile(
    r"\.(?:png|jpe?g|gif|webp|bmp|ico|svg|json|geojson|bin|dat|csv|css|m?js"
    r"|woff2?|ttf|eot|otf|mp3|ogg|wav|mp4|webm|wasm|ktx2?|glb|gltf|ktx|dds|xml|txt)$",
    re.I,
)
RE_ATTR = re.compile(
    r"""(?:href|src|poster|action|data-src|data-original|data-url|content)\s*=\s*["']([^"']+)["']""",
    re.I,
)
RE_SRCSET = re.compile(r"""srcset\s*=\s*["']([^"']+)["']""", re.I)
RE_CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""", re.I)
RE_CSS_IMPORT = re.compile(r"""@import\s+(?:url\()?\s*['"]?([^'")]+)""", re.I)
RE_JS_STR = re.compile(r"""["'`]([^"'`\r\n]{1,300})["'`]""")
RE_SKIP_SCHEME = re.compile(r"^(?:data|blob|javascript|mailto|tel|about|ws|wss|file):", re.I)


# ---------------------------------------------------------------- URL 工具

def split_host(url):
    return (urllib.parse.urlsplit(url).netloc or "").lower()


def host_variants(host):
    if host.startswith("www."):
        return {host, host[4:]}
    return {host, "www." + host}


def make_absolute(base, raw):
    raw = raw.strip()
    if not raw or raw.startswith("#") or RE_SKIP_SCHEME.match(raw):
        return None
    try:
        return urllib.parse.urljoin(base, raw)
    except ValueError:
        return None


def local_path_for(out, url):
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parts.path or "/")
    if path.endswith("/"):
        path += "index.html"
    rel = path.lstrip("/").replace("\\", "/")
    rel = "/".join(seg for seg in rel.split("/") if seg not in ("", ".", ".."))
    return os.path.join(out, *(rel or "index.html").split("/"))


# ---------------------------------------------------------------- 链接抽取

def _classify(s):
    if not s or len(s) < 2 or len(s) > 400:
        return None
    if any(c in s for c in " \t\r\n\"'<>"):
        return None
    if "{" in s or "}" in s:
        return "template"
    if s.startswith(("/", "./", "../", "http://", "https://", "//")):
        return "url"
    if ASSET_EXT_RE.search(s):
        return "url"
    return None


def extract_links(doc_url, text, content_type):
    urls, templates = set(), set()
    ct = (content_type or "").lower()
    head = text[:400].lower()

    def add(raw):
        kind = _classify(raw.strip())
        if kind == "template":
            templates.add(raw.strip())
        elif kind == "url":
            absu = make_absolute(doc_url, raw)
            if absu:
                u = urllib.parse.urlsplit(absu)
                if u.scheme in ("http", "https"):
                    urls.add(urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, u.query, "")))

    if "html" in ct or "<html" in head or "<!doctype" in head:
        for m in RE_ATTR.finditer(text):
            add(m.group(1))
        for m in RE_SRCSET.finditer(text):
            for cand in m.group(1).split(","):
                add(cand.strip().split(" ")[0])

    if "css" in ct:
        for m in RE_CSS_URL.finditer(text):
            add(m.group(1))
        for m in RE_CSS_IMPORT.finditer(text):
            add(m.group(1))

    if any(k in ct for k in ("javascript", "ecmascript", "json", "html", "css")):
        for m in RE_JS_STR.finditer(text):
            add(m.group(1))

    return urls, templates


# ---------------------------------------------------------------- 抓取核心

def build_opener(proxy):
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})]
    return urllib.request.build_opener(*handlers)


class Crawler:
    def __init__(self, args):
        self.a = args
        self.opener = build_opener(args.proxy)
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.seen = set()
        self.active = 0
        self.ok = 0
        self.skipped = 0
        self.failed = 0
        self.failures = []
        self.templates = set()
        self.external = set()
        self.bytes_total = 0

    # -- 调度 --
    def enqueue(self, url):
        u = url.split("#")[0]
        with self.lock:
            if u in self.seen:
                return
            self.seen.add(u)
            self.active += 1
        self.q.put(u)

    def run(self, seeds):
        for s in seeds:
            self.enqueue(s)
        threads = [
            threading.Thread(target=self._worker, daemon=True)
            for _ in range(max(1, self.a.jobs))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def _worker(self):
        while True:
            with self.lock:
                if self.active == 0:
                    return
            try:
                url = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._process(url)
            except Exception as e:  # noqa: BLE001
                with self.lock:
                    self.failed += 1
                    self.failures.append((url, f"{type(e).__name__}: {e}"))
            finally:
                with self.lock:
                    self.active -= 1

    # -- 单个 URL --
    def _allowed(self, url):
        host = split_host(url)
        path = urllib.parse.urlsplit(url).path or "/"
        if not self.a.all_hosts and host not in self.a.allowed_hosts:
            with self.lock:
                self.external.add(host)
            return False
        if self.a.prefix != "/" and not path.startswith(self.a.prefix):
            return False
        return True

    def _process(self, url):
        if not self._allowed(url):
            return

        dest = local_path_for(self.a.out, url)
        is_text = dest.lower().endswith(tuple(TEXT_EXT))

        # 已存在：跳过下载，但仍解析链接（保证续传时能继续扩散）
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            with self.lock:
                self.skipped += 1
            if is_text:
                try:
                    self._parse(url, open(dest, "rb").read(), "")
                except Exception:
                    pass
            return

        body = None
        ctype = ""
        last = ""
        for attempt in range(1, self.a.retries + 1):
            try:
                status, ctype, body = self._fetch(url)
                break
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code in (404, 410):
                    break
                if e.code in (403, 429, 503):
                    time.sleep(min(30, 3 * attempt) + random.uniform(0, 1))
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
                last = f"{type(e).__name__}: {e}"
                time.sleep(attempt + random.uniform(0, 1))
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
            body = None

        if body is None:
            with self.lock:
                self.failed += 1
                self.failures.append((url, last))
            return

        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as f:
            f.write(body)

        with self.lock:
            self.ok += 1
            self.bytes_total += len(body)
            n = self.ok + self.skipped
            if n % 100 == 0:
                print(f"  ... 已处理 {n} 个，当前 {url.split('mathartbang.com')[-1]}", flush=True)

        if is_text:
            self._parse(url, body, ctype)

    def _parse(self, url, body, ctype):
        try:
            text = body.decode("utf-8", "replace")
        except Exception:
            return
        urls, tpl = extract_links(url, text, ctype)
        with self.lock:
            self.templates |= tpl
        skips = self.a.skip_prefix
        for u in urls:
            if skips and any(urllib.parse.urlsplit(u).path.startswith(p) for p in skips):
                continue
            self.enqueue(u)

    def _fetch(self, url):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
                "Referer": "/".join(url.split("/")[:3]) + "/",
            },
        )
        with self.opener.open(req, timeout=self.a.timeout) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()


# ---------------------------------------------------------------- 入口

def main(argv=None):
    ap = argparse.ArgumentParser(description="静态站点镜像（多线程、可续传）")
    ap.add_argument("--seeds", nargs="*", default=None, help="起始 URL")
    ap.add_argument("--seeds-file", default=None, help="从文件读取起始 URL，一行一个")
    ap.add_argument("--out", default="site", help="输出目录")
    ap.add_argument("--proxy", default=None, help="HTTP(S) 代理")
    ap.add_argument("--prefix", default="/deca/", help="只抓该路径前缀；/ 表示整站")
    ap.add_argument("--skip-prefix", nargs="*", default=[],
                    help="不抓这些路径前缀下的。只作用于「从页面里发现的链接」，"
                         "不影响 --seeds/--seeds-file 里明确列出的 URL")
    ap.add_argument("--jobs", type=int, default=8, help="并发线程数")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--all-hosts", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)

    # 给了 --seeds 或 --seeds-file 就完全按给的来，不要偷偷加默认种子
    # （否则第二遍会顺着默认种子把整站重爬一遍）
    if args.seeds:
        seeds = list(args.seeds)
    elif args.seeds_file:
        seeds = []
    else:
        seeds = list(DEFAULT_SEEDS)
    if args.seeds_file:
        with open(args.seeds_file, encoding="utf-8") as f:
            seeds += [l.strip() for l in f if l.strip() and not l.startswith("#")]
    seeds = [s for s in dict.fromkeys(seeds)]
    if not seeds:
        print("[!] 没有起始 URL（--seeds 为空且 --seeds-file 里没内容）", file=sys.stderr)
        return 1

    args.allowed_hosts = set()
    for s in seeds:
        args.allowed_hosts |= host_variants(split_host(s))

    print(f"[*] 输出目录 : {os.path.abspath(args.out)}")
    print(f"[*] 主机范围 : {', '.join(sorted(args.allowed_hosts))}  前缀 {args.prefix}")
    print(f"[*] 起始 URL : {len(seeds)} 个   并发 {args.jobs}")
    if args.proxy:
        print(f"[*] 代理     : {args.proxy}")
    if args.dry_run:
        for s in seeds:
            print("  -", s)
        return 0
    print(flush=True)

    c = Crawler(args)
    t0 = time.time()
    c.run(seeds)
    dt = time.time() - t0

    print()
    print(f"[=] 完成：下载 {c.ok}，跳过 {c.skipped}，失败 {c.failed}，"
          f"共 {c.bytes_total / 1048576:.1f} MB，用时 {dt / 60:.1f} 分钟")

    if c.external:
        print(f"[!] 站外主机（未抓取）：{', '.join(sorted(c.external))}")
    if c.templates:
        print(f"[!] 含占位符的 URL 模板 {len(c.templates)} 条：")
        for t in sorted(c.templates)[:25]:
            print("    ", t)
    if c.failures:
        print(f"[!] 失败 {len(c.failures)} 条（前 20 条）：")
        for u, e in c.failures[:20]:
            print(f"    {e:28s} {u}")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "downloaded": c.ok,
                    "skipped": c.skipped,
                    "failed": c.failed,
                    "failures": [{"url": u, "error": e} for u, e in c.failures],
                    "external_hosts": sorted(c.external),
                    "templates": sorted(c.templates),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"[*] 报告写入 {args.report}")

    # 只要下到了东西就算成功——个别 404 不该让整条流水线失败
    return 0 if c.ok > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
