#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
import argparse
import csv
import os
import re
import signal
import sys
import time
from collections import defaultdict
from urllib.parse import urljoin, urlsplit, urlunsplit, urldefrag

from bs4 import BeautifulSoup
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
import tldextract
from urllib.robotparser import RobotFileParser

console = Console()

BINARY_EXTS = {
    ".jpg",".jpeg",".png",".gif",".webp",".svg",".ico",".bmp",
    ".mp4",".webm",".mp3",".wav",".ogg",".m4a",".avi",".mov",
    ".zip",".rar",".7z",".gz",".tar",".tgz",
    ".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",
    ".ttf",".woff",".woff2",".eot",
    ".exe",".msi",".dmg",".apk",".iso"
}

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; LinkHarvester/1.0; +https://example.local)"
)

def ensure_url(u: str) -> str:
    """স্কিম না দিলে https:// ধরবে"""
    u = u.strip()
    if not u:
        return u
    if "://" not in u:
        u = "https://" + u
    return u

def normalize_url(u: str, base: str = None) -> str:
    """রিলেটিভ->অ্যাবসোলিউট, ফ্রাগমেন্ট রিমুভ, ডিফল্ট পোর্ট বাদ, পাথ নরমালাইজ"""
    if base:
        u = urljoin(base, u)
    u, _ = urldefrag(u)  # remove #fragment
    parts = urlsplit(u)
    scheme = parts.scheme.lower() if parts.scheme else "http"
    netloc = parts.netloc.lower()

    # strip default ports
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    path = re.sub(r"/+", "/", parts.path) or "/"
    query = parts.query
    return urlunsplit((scheme, netloc, path, query, ""))

def is_http_url(u: str) -> bool:
    s = urlsplit(u).scheme.lower()
    return s in ("http", "https")

def looks_like_binary(u: str) -> bool:
    path = urlsplit(u).path.lower()
    for ext in BINARY_EXTS:
        if path.endswith(ext):
            return True
    return False

def extract_links(html: str, base_url: str) -> set:
    """HTML থেকে বিভিন্ন ট্যাগ/অ্যাট্রিবিউটের URL সংগ্রহ"""
    soup = BeautifulSoup(html, "html.parser")
    urls = set()

    pairs = [
        ("a", "href"),
        ("link", "href"),
        ("script", "src"),
        ("img", "src"),
        ("iframe", "src"),
        ("video", "src"),
        ("audio", "src"),
        ("source", "src"),
        ("form", "action"),
    ]

    for tag, attr in pairs:
        for el in soup.find_all(tag):
            v = el.get(attr)
            if not v:
                continue
            urls.add(normalize_url(v, base_url))
            # srcset (source/img)
            if attr in ("src",) and el.has_attr("srcset"):
                srcset = el["srcset"]
                for chunk in srcset.split(","):
                    u = chunk.strip().split(" ")[0]
                    if u:
                        urls.add(normalize_url(u, base_url))

    # meta http-equiv=refresh
    for meta in soup.find_all("meta"):
        hv = meta.get("http-equiv") or meta.get("http_equiv")
        if hv and str(hv).lower() == "refresh":
            content = meta.get("content", "")
            m = re.search(r"url=(.+)", content, flags=re.I)
            if m:
                urls.add(normalize_url(m.group(1), base_url))

    return {u for u in urls if is_http_url(u)}

class Crawler:
    def __init__(
        self,
        start_url: str,
        workers: int = 12,
        max_pages: int = 10000,
        respect_robots: bool = True,
        include_subdomains: bool = True,
        timeout: int = 20,
        user_agent: str = DEFAULT_UA,
        verbose: bool = True,
        outdir: str = ".",
    ):
        self.start_url = ensure_url(start_url)
        self.workers = workers
        self.max_pages = max_pages
        self.respect_robots = respect_robots
        self.include_subdomains = include_subdomains
        self.timeout = timeout
        self.user_agent = user_agent
        self.verbose = verbose
        self.outdir = outdir

        self.session: aiohttp.ClientSession | None = None
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.visited_pages: set[str] = set()  # internal HTML pages fetched
        self.all_links: set[str] = set()      # all discovered http(s) links
        self.internal_links: set[str] = set()
        self.external_links: set[str] = set()
        self.errors = 0
        self.skipped_by_robots = 0
        self.status_counts = defaultdict(int)
        self.last_found = ""
        self._stop = False
        self.write_lock = asyncio.Lock()

        # domain rules
        sp = urlsplit(self.start_url)
        self.start_host = sp.hostname or sp.netloc
        ext = tldextract.extract(self.start_url)
        self.reg_domain = ext.registered_domain or self.start_host
        self.file_stem = self.reg_domain  # for outputs

        # outputs
        os.makedirs(self.outdir, exist_ok=True)
        self.txt_path = os.path.join(self.outdir, f"{self.file_stem}-links.txt")
        self.csv_path = os.path.join(self.outdir, f"{self.file_stem}-links.csv")
        self.csv_file = None
        self.csv_writer = None

        self.live: Live | None = None
        self.rp: RobotFileParser | None = None

    def url_is_internal(self, u: str) -> bool:
        host = urlsplit(u).hostname or ""
        if not host:
            return False
        if self.include_subdomains:
            return host == self.start_host or host.endswith("." + self.reg_domain) or host == self.reg_domain
        else:
            return host == self.start_host

    def render_panel(self):
        t = Table.grid(padding=(0, 1))
        t.add_row("Target", f"[bold]{self.start_host}[/]")
        t.add_row("Found links", f"{len(self.all_links)}  (internal: {len(self.internal_links)} | external: {len(self.external_links)})")
        t.add_row("Pages crawled", f"{len(self.visited_pages)} / {self.max_pages}")
        t.add_row("Queue size", f"{self.queue.qsize()}")
        if self.respect_robots:
            t.add_row("Robots disallowed", f"{self.skipped_by_robots}")
        if self.errors:
            t.add_row("Errors", f"{self.errors}")
        t.add_row("Workers", f"{self.workers}")
        t.add_row("Saving to", f"{self.txt_path}  &  {self.csv_path}")
        if self.last_found:
            t.add_row("Last found", f"{self.last_found}")
        t.add_row("", "[dim]Press Ctrl+C to stop (progress will be saved)[/dim]")
        return Panel(t, title="[cyan]Link Harvester[/cyan]", border_style="cyan")

    async def _init_outputs(self):
        # open CSV once
        self.csv_file = open(self.csv_path, "w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(["link", "internal", "source_page"])

        # ensure empty/overwrite .txt
        open(self.txt_path, "w", encoding="utf-8").close()

    async def _append_outputs(self, link: str, internal: bool, source: str):
        async with self.write_lock:
            # text file: just the link
            with open(self.txt_path, "a", encoding="utf-8") as f:
                f.write(link + "\n")
            # csv
            self.csv_writer.writerow([link, "yes" if internal else "no", source])
            self.csv_file.flush()

    async def _load_robots(self):
        self.rp = RobotFileParser()
        if not self.respect_robots:
            self.rp.parse([])  # allow all
            return
        try:
            sp = urlsplit(self.start_url)
            robots_url = f"{sp.scheme}://{sp.netloc}/robots.txt"
            async with self.session.get(robots_url, headers={"User-Agent": self.user_agent}, timeout=self.timeout) as resp:
                if resp.status == 200:
                    txt = await resp.text(errors="ignore")
                    self.rp.parse(txt.splitlines())
                else:
                    # no robots => allow all
                    self.rp.parse([])
        except Exception:
            self.rp.parse([])  # on error, allow all

    async def run(self):
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        connector = aiohttp.TCPConnector(limit_per_host=self.workers, ssl=None)  # default SSL, set ssl=False if needed
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            self.session = session
            await self._init_outputs()
            await self._load_robots()

            # seed
            await self.queue.put(self.start_url)

            # CTRL+C graceful stop
            loop = asyncio.get_event_loop()
            try:
                loop.add_signal_handler(signal.SIGINT, self._request_stop)
                if hasattr(signal, "SIGTERM"):
                    loop.add_signal_handler(signal.SIGTERM, self._request_stop)
            except NotImplementedError:
                # Windows may not support add_signal_handler for SIGTERM
                pass

            workers = [asyncio.create_task(self.worker(i)) for i in range(self.workers)]
            with Live(self.render_panel(), console=console, refresh_per_second=6) as live:
                self.live = live
                # monitor loop
                while not self._stop:
                    await asyncio.sleep(0.3)
                    live.update(self.render_panel())
                    # finish if done
                    if self.queue.empty() and all(w.done() for w in workers):
                        break

                # if stop requested, cancel workers
                for w in workers:
                    if not w.done():
                        w.cancel()
                await asyncio.gather(*workers, return_exceptions=True)

            # close csv
            if self.csv_file:
                self.csv_file.close()

    def _request_stop(self):
        self._stop = True

    async def worker(self, idx: int):
        while not self._stop:
            try:
                url = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # idle
                if self.queue.empty():
                    return
                continue

            try:
                await self.process_page(url)
            except Exception as e:
                self.errors += 1
            finally:
                self.queue.task_done()

    async def process_page(self, url: str):
        # ডুপ্লিকেট চেক
        if url in self.visited_pages:
            return
        if len(self.visited_pages) >= self.max_pages:
            return

        # robots
        if self.respect_robots and self.rp and not self.rp.can_fetch(self.user_agent, url):
            self.skipped_by_robots += 1
            return

        self.visited_pages.add(url)

        try:
            headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
            async with self.session.get(url, headers=headers, allow_redirects=True) as resp:
                self.status_counts[resp.status] += 1
                ctype = (resp.headers.get("content-type") or "").lower()
                # HTML না হলে শুধু রেকর্ড করে বেরিয়ে যান
                if "text/html" not in ctype:
                    return
                html = await resp.text(errors="ignore")
        except Exception:
            self.errors += 1
            return

        # লিংক এক্সট্রাক্ট
        links = extract_links(html, url)
        for link in links:
            if link in self.all_links:
                continue

            internal = self.url_is_internal(link)
            self.all_links.add(link)
            if internal:
                self.internal_links.add(link)
            else:
                self.external_links.add(link)

            self.last_found = link

            # রিয়েল-টাইম কনসোল আউটপুট
            if self.verbose:
                console.print(("[green]+ INTERNAL[/green] " if internal else "[yellow]+ EXTERNAL[/yellow] ") + link)

            # ফাইলেও সঙ্গে সঙ্গে লিখে ফেলি
            await self._append_outputs(link, internal, url)

            # কিউতে নতুন পেজ যোগ (শুধু ইন্টারনাল + নন-বাইনারি + http[s])
            if internal and not looks_like_binary(link) and is_http_url(link):
                if link not in self.visited_pages:
                    await self.queue.put(link)

def main():
    parser = argparse.ArgumentParser(
        description="Real-time website link extractor (saves to domain-named files)"
    )
    parser.add_argument("url", help="Target website URL (e.g., https://example.com)")
    parser.add_argument("-w", "--workers", type=int, default=12, help="Concurrent workers (default: 12)")
    parser.add_argument("-m", "--max-pages", type=int, default=10000, help="Max pages to crawl (default: 10000)")
    parser.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt (default: respect)")
    parser.add_argument("--no-subdomains", action="store_true", help="Only crawl exact host, exclude subdomains")
    parser.add_argument("--timeout", type=int, default=20, help="Request timeout seconds (default: 20)")
    parser.add_argument("--ua", default=DEFAULT_UA, help="Custom User-Agent")
    parser.add_argument("--quiet", action="store_true", help="No per-link console lines (only stats panel)")
    parser.add_argument("-o", "--outdir", default=".", help="Output directory (default: current folder)")

    args = parser.parse_args()

    crawler = Crawler(
        start_url=args.url,
        workers=args.workers,
        max_pages=args.max_pages,
        respect_robots=not args.ignore_robots,
        include_subdomains=not args.no_subdomains,
        timeout=args.timeout,
        user_agent=args.ua,
        verbose=not args.quiet,
        outdir=args.outdir,
    )

    try:
        asyncio.run(crawler.run())
    except KeyboardInterrupt:
        pass
    finally:
        console.print("\n[bold]Done.[/bold]")

if __name__ == "__main__":
    main()