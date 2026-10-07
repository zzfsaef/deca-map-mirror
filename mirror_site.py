#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mirror_site.py —— 把静态站点（GitHub Pages 之类）完整镜像到本地。

为什么需要它：www.mathartbang.com 是 GitHub Pages 静态站，页面加载后由 JS
再去抓数据文件。wget / 浏览器"另存为"都抓不全这些运行时请求，所以这里会同时
解析 HTML、CSS 和 JS 里出现的 URL。

镜像后的目录结构和网址路径一一对应（/deca/hp/map.html -> <out>/deca/hp/map.html），
因此直接把 <out> 当成站点根目录起服务即可，不需要改写链接。

用法示例：
    python mirror_site.py
    python mirror_site.py --proxy http://127.0.0.1:7890
    python mirror_site.py --out site --prefix /deca/
    python mirror_site.py --dry-run          # 只列出会抓的 URL，不下载
中断后重新运行会自动跳过已下载的文件（可续传）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

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


# ---------------------------------------------------------------- URL 处理

def split_host(url: str) -> str:
    return (urllib.parse.urlsplit(url).netloc or "").lower()


def host_variants(host: str):
    """www.example.com <-> example.com"""
    if host.startswith("www."):
        return {host, host[4:]}
    return {host, "www." + host}


def make_absolute(base: str, raw: str):
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None
    if RE_SKIP_SCHEME.match(raw):
        return None
    try:
        return urllib.parse.urljoin(base, raw)
    except ValueError:
        return None


def local_path_for(out: str, url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parts.path or "/")
    if path.endswith("/"):
        path += "index.html"
    rel = path.lstrip("/").replace("\\", "/")
    # 防止目录穿越
    rel = "/".join(seg for seg in rel.split("/") if seg not in ("", ".", ".."))
    if not rel:
        rel = "index.html"
    return os.path.join(out, *rel.split("/"))


# ---------------------------------------------------------------- 链接抽取

def _is_candidate(s: str):
    """返回 'url' / 'template' / None"""
    if not s or len(s) < 2 or len(s) > 400:
        return None
    if any(c in s for c in " \t\r\n\"'<>"):
        return None
    if "{" in s or "}" in s:
        # 形如 data/{reserve}/tiles/{z}/{x}.png —— 无法直接抓，单独汇报
        return "template"
    if s.startswith(("/", "./", "../", "http://", "https://", "//")):
        return "url"
    if ASSET_EXT_RE.search(s):
        return "url"
    return None


def extract_links(doc_url: str, text: str, content_type: str):
    """从 HTML / CSS / JS / JSON 文本里抽出候选 URL。返回 (urls, templates)"""
    urls, templates = set(), set()
    ct = (content_type or "").lower()

    def add(raw):
        s = raw.strip()
        kind = _is_candidate(s)
        if kind == "template":
            templates.add(s)
        elif kind == "url":
            absu = make_absolute(doc_url, s)
            if absu:
                u = urllib.parse.urlsplit(absu)
                if u.scheme in ("http", "https"):
                    urls.add(urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, u.query, "")))

    if "html" in ct or "<html" in text[:400].lower() or "<!doctype" in text[:400].lower():
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

    # JS / JSON / 内联脚本：字符串字面量里出现的路径
    if any(k in ct for k in ("javascript", "ecmascript", "json")) or "html" in ct or "css" in ct:
        for m in RE_JS_STR.finditer(text):
            add(m.group(1))

    return urls, templates


# ---------------------------------------------------------------- 下载

def build_opener(proxy: str | None):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))  # 忽略系统代理，行为可预期
    return urllib.request.build_opener(*handlers)


def fetch(opener, url: str, timeout: float):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Referer": "/".join(url.split("/")[:3]) + "/",
        },
    )
    with opener.open(req, timeout=timeout) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


# ---------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="镜像静态站点到本地（保持 URL 目录结构）")
    ap.add_argument("--seeds", nargs="*", default=DEFAULT_SEEDS, help="起始页面")
    ap.add_argument("--out", default="site", help="输出目录（默认 ./site）")
    ap.add_argument("--proxy", default=None, help="HTTP(S) 代理，如 http://127.0.0.1:7890")
    ap.add_argument("--prefix", default="/deca/", help="只抓该路径前缀下的内容；用 / 表示整站")
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.05, help="每次请求间隔秒数")
    ap.add_argument("--all-hosts", action="store_true", help="允许跨主机抓取（默认只抓同主机）")
    ap.add_argument("--dry-run", action="store_true", help="只列出 URL，不下载")
    ap.add_argument("--report", default=None, help="把抓取结果写成 JSON 报告")
    args = ap.parse_args(argv)

    seeds = [s for s in args.seeds]
    allowed_hosts = set()
    for s in seeds:
        allowed_hosts |= host_variants(split_host(s))
    primary_host = split_host(seeds[0])
    prefix = args.prefix or "/"

    opener = build_opener(args.proxy)
    os.makedirs(args.out, exist_ok=True)

    queue = deque(seeds)
    seen: set[str] = set()
    ok, skipped, failed = 0, 0, 0
    failures: list[tuple[str, str]] = []
    all_templates: set[str] = set()
    external_hosts: set[str] = set()

    print(f"[*] 输出目录 : {os.path.abspath(args.out)}")
    print(f"[*] 抓取范围 : {', '.join(sorted(allowed_hosts))}  路径前缀 {prefix}")
    if args.proxy:
        print(f"[*] 代理     : {args.proxy}")
    print()

    while queue:
        url = queue.popleft()
        key = url.split("#")[0]
        if key in seen:
            continue
        seen.add(key)

        host = split_host(url)
        path = urllib.parse.urlsplit(url).path or "/"
        if not args.all_hosts and host not in allowed_hosts:
            external_hosts.add(host)
            continue
        if prefix != "/" and not path.startswith(prefix):
            continue

        dest = local_path_for(args.out, url)

        if args.dry_run:
            print("  -", url)
            continue

        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            skipped += 1
            # 已存在也解析一次，继续扩散（不然续传会断链）
            try:
                with open(dest, "rb") as f:
                    body = f.read()
                text = body.decode("utf-8", "replace")
                urls, tpl = extract_links(url, text, "")
                all_templates |= tpl
                for u in sorted(urls):
                    if u not in seen:
                        queue.append(u)
            except Exception:
                pass
            continue

        last_err = ""
        for attempt in range(1, args.retries + 1):
            try:
                status, ctype, body = fetch(opener, url, args.timeout)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(body)
                ok += 1
                size_kb = len(body) / 1024
                print(f"  [{status}] {size_kb:9.1f} KB  {path}")

                if any(dest.lower().endswith(e) for e in TEXT_EXT):
                    text = body.decode("utf-8", "replace")
                    urls, tpl = extract_links(url, text, ctype)
                    all_templates |= tpl
                    for u in sorted(urls):
                        if u not in seen:
                            queue.append(u)
                break
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
                if e.code in (403, 404, 410):
                    break
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
                last_err = f"{type(e).__name__}: {e}"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"
            if attempt < args.retries:
                time.sleep(1.0 * attempt)

        if last_err:
            failed += 1
            failures.append((url, last_err))
            print(f"  [!!] {last_err:24s} {path}", file=sys.stderr)

        if args.delay:
            time.sleep(args.delay)

    print()
    print(f"[=] 完成：下载 {ok}，跳过(已存在) {skipped}，失败 {failed}")

    if external_hosts:
        print(f"[!] 发现站外资源主机（未抓取）：{', '.join(sorted(external_hosts))}")

    if all_templates:
        print()
        print("[!] 发现含占位符的 URL 模板，需要手动展开后再抓（可能是地图瓦片）：")
        for t in sorted(all_templates)[:40]:
            print("    ", t)
        if len(all_templates) > 40:
            print(f"     ... 另有 {len(all_templates) - 40} 条")

    if failures:
        print()
        print("[!] 失败清单（前 30 条）：")
        for u, e in failures[:30]:
            print(f"    {e:26s} {u}")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "downloaded": ok,
                    "skipped": skipped,
                    "failed": failed,
                    "failures": [{"url": u, "error": e} for u, e in failures],
                    "external_hosts": sorted(external_hosts),
                    "templates": sorted(all_templates),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"[*] 报告已写入 {args.report}")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
