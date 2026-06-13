import re
import time
from dataclasses import dataclass, field
from typing import Optional
from bs4 import BeautifulSoup, Tag

from utils.http_utils import get_http, RateLimiter
from utils.html_utils import remove_elements, remove_load_failed_placeholder, remove_line_breaks, wrap_duokan_image
from utils.chapterlog import ChapterLogResolver, reverse_shuffle, DEFAULT_SEED_MULTIPLIER, DEFAULT_SEED_OFFSET, DEFAULT_A, DEFAULT_C, DEFAULT_MOD, DEFAULT_FIXED_LENGTH


DOMAIN = "https://www.linovelib.com"
ID_RE = re.compile(r"(?:linovelib|bilinovel)\.com/(?:novel|download)/(\d+)")
CHAPTER_ID_RE = re.compile(r"chapterid:'(\d+)")
PAGE_ID_RE = re.compile(r"/novel/\d+/(\d+(?:_\d+)?)\.html")


def _extract_page_id(url: str) -> Optional[str]:
    m = PAGE_ID_RE.search(url)
    return m.group(1) if m else None


def _first_of(soup: BeautifulSoup, *selectors: str) -> Optional[Tag]:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el
    return None


@dataclass
class Novel:
    id: str = ""
    url: str = ""
    title: str = ""
    alias: str = ""
    author: str = ""
    cover_url: str = ""
    tags: list[str] = field(default_factory=list)
    publisher: str = ""
    status: str = ""
    description: str = ""


@dataclass
class Volume:
    name: str = ""
    cover: str = ""
    chapters: list["Chapter"] = field(default_factory=list)


@dataclass
class Chapter:
    name: str
    url: Optional[str] = None
    volume: Optional[Volume] = None
    pages: list[str] = field(default_factory=list)


@dataclass
class Catalog:
    novel: Novel
    volumes: list[Volume] = field(default_factory=list)


class BiliNovelSource:
    def __init__(self):
        self._http = get_http()
        self._chapterlog = ChapterLogResolver(DOMAIN)
        self._rate_limiter = RateLimiter(15, 60)
        self._img_rate_limiter = RateLimiter(10, 1)

    @staticmethod
    def supports(url: str) -> bool:
        return bool(ID_RE.search(url))

    @staticmethod
    def _extract_id(url: str) -> str:
        m = ID_RE.search(url)
        if not m:
            raise ValueError(f"Unsupported URL: {url}")
        return m.group(1)

    def get_novel(self, url: str) -> Novel:
        novel_id = self._extract_id(url)
        self._rate_limiter.acquire()
        html = self._http.get(f"{DOMAIN}/novel/{novel_id}.html")
        soup = BeautifulSoup(html, "lxml")

        novel = Novel()
        novel.id = novel_id
        novel.url = url

        title_el = _first_of(soup, ".book-title", ".book-name")
        novel.title = title_el.get_text(strip=True) if title_el else "Unknown"

        backup = soup.select_one(".backupname .bkname-body.gray")
        if backup:
            novel.alias = backup.get_text(strip=True)

        img = _first_of(soup, ".book-layout img", ".book-img img", ".book-detail .book-img img")
        if img:
            novel.cover_url = img.get("data-original") or img.get("data-src") or img.get("src")

        tags = soup.select(".book-cell .book-meta span em")
        if not tags:
            tags = soup.select(".book-label span a")
        novel.tags = [el.get_text(strip=True) for el in tags]

        pub = soup.select_one(".tag-small.orange")
        if pub:
            novel.publisher = pub.get_text(strip=True)

        status_el = _first_of(soup, ".book-label .state")
        if status_el:
            novel.status = status_el.get_text(strip=True)
        else:
            meta = soup.select_one(".book-cell .book-meta+.book-meta")
            if meta:
                texts = [n.strip() for n in meta.find_all(text=True) if n.strip()]
                if texts:
                    novel.status = texts[-1]

        author_el = _first_of(soup, ".book-rand-a span")
        if author_el:
            novel.author = author_el.get_text(strip=True)
        else:
            author_meta = soup.select_one('meta[name="author"]')
            if author_meta and author_meta.get("content"):
                novel.author = author_meta["content"]

        desc = soup.select_one("#bookSummary content")
        if desc:
            novel.description = desc.get_text(strip=True)
        else:
            desc = soup.select_one(".book-dec p")
            if desc:
                novel.description = desc.get_text(strip=True)

        return novel

    def get_catalog(self, novel: Novel) -> Catalog:
        self._rate_limiter.acquire()
        html = self._http.get(f"{DOMAIN}/novel/{novel.id}/catalog")
        soup = BeautifulSoup(html, "lxml")
        catalog = Catalog(novel=novel)

        lis = soup.select(".volume-chapters > li")
        if lis:
            return self._parse_mobile_catalog(soup, catalog)

        return self._parse_pc_catalog(soup, catalog)

    def _parse_mobile_catalog(self, soup: BeautifulSoup, catalog: Catalog) -> Catalog:
        volume: Optional[Volume] = None
        if not soup.select_one(".chapter-bar"):
            volume = Volume(name="")

        for li in soup.select(".volume-chapters > li"):
            classes = li.get("class", [])
            if "chapter-bar" in classes:
                if volume is not None:
                    catalog.volumes.append(volume)
                volume = Volume(name=li.get_text(strip=True))
            elif "volume-cover" in classes:
                if volume is not None:
                    a = li.select_one("a")
                    if a:
                        img = a.select_one("img")
                        if img and img.get("src"):
                            volume.cover = img["src"]
            elif "jsChapter" in classes:
                self._add_chapter(li, volume, catalog)

        if volume is not None:
            catalog.volumes.append(volume)
        return catalog

    def _parse_pc_catalog(self, soup: BeautifulSoup, catalog: Catalog) -> Catalog:
        container = soup.select_one("#volume-list")
        if not container:
            container = soup.select_one(".volume-list")
        if not container:
            raise RuntimeError("Cannot find catalog volume list")

        for div in container.select(":scope > div.volume"):
            h2 = div.select_one("h2.v-line a")
            volume_name = h2.get_text(strip=True) if h2 else ""
            volume = Volume(name=volume_name)

            cover_a = div.select_one("a.volume-cover img")
            if cover_a:
                src = cover_a.get("data-original") or cover_a.get("src")
                if src:
                    volume.cover = src

            chapter_list = div.select_one("ul.chapter-list")
            if chapter_list:
                for li in chapter_list.find_all("li", class_="col-4"):
                    link = li.select_one("a")
                    if not link:
                        continue
                    name = link.get_text(strip=True)
                    chapter = self._make_chapter(link, name)
                    if chapter:
                        chapter.volume = volume
                        volume.chapters.append(chapter)

            if volume.chapters:
                catalog.volumes.append(volume)

        if not catalog.volumes:
            vol = Volume(name="")
            for ul in soup.select("ul.chapter-list"):
                for li in ul.find_all("li", class_="col-4"):
                    self._add_chapter(li, vol, catalog)

        return catalog

    def _add_chapter(self, li: Tag, volume: Optional[Volume], catalog: Catalog) -> None:
        link = li.select_one("a")
        if not link:
            return
        name = link.get_text(strip=True)
        chapter = self._make_chapter(link, name)
        if chapter and volume is not None:
            chapter.volume = volume
            volume.chapters.append(chapter)

    @staticmethod
    def _make_chapter(link: Optional[Tag], name: str) -> Optional[Chapter]:
        if not link:
            return None
        href = link.get("href", "")
        chapter_url = None
        if href and "javascript" not in href:
            chapter_url = f"{DOMAIN}{href}" if href.startswith("/") else href
        return Chapter(name=name, url=chapter_url)

    def get_chapter_html(self, chapter: Chapter) -> str:
        if not chapter.url:
            chapter.url = self._resolve_chapter_url(chapter)
        if not chapter.url:
            raise RuntimeError(f"Cannot resolve URL for chapter: {chapter.name}")

        parts = []
        next_page: Optional[str] = chapter.url

        while next_page:
            page = self._fetch_chapter_page(next_page)
            if page.title and page.title != chapter.name and "〇" not in page.title:
                chapter.name = page.title
            for content in page.contents:
                parts.append(str(content))
            next_page = page.next_page_url

        html = "\n".join(parts)
        soup = BeautifulSoup(f"<div>{html}</div>", "lxml")
        root = soup.div

        remove_load_failed_placeholder(root)
        remove_line_breaks(root)
        self._fix_image_srcs(root)

        return str(root)

    def _resolve_chapter_url(self, chapter: Chapter) -> Optional[str]:
        if chapter.url and chapter.url.strip():
            return chapter.url

        catalog = chapter.volume.catalog if chapter.volume else None
        if not catalog:
            return None

        all_chapters = []
        for vol in catalog.volumes:
            all_chapters.extend(vol.chapters)

        try:
            idx = all_chapters.index(chapter)
        except ValueError:
            return None

        next_ch = all_chapters[idx + 1] if idx + 1 < len(all_chapters) else None
        if next_ch and next_ch.url:
            page = self._fetch_chapter_page(next_ch.url)
            if page.prev_chapter_url:
                return page.prev_chapter_url

        prev_ch = all_chapters[idx - 1] if idx > 0 else None
        if prev_ch and prev_ch.url:
            page = self._fetch_chapter_page(prev_ch.url)
            next_page = page.next_page_url
            for _ in range(20):
                if next_page is None:
                    return page.next_chapter_url
                page = self._fetch_chapter_page(next_page)
                next_page = page.next_page_url

        return None

    @dataclass
    class _ChapterPage:
        title: Optional[str] = None
        contents: list = field(default_factory=list)
        prev_page_url: Optional[str] = None
        next_page_url: Optional[str] = None
        prev_chapter_url: Optional[str] = None
        next_chapter_url: Optional[str] = None

    def _fetch_chapter_page(self, url: str) -> _ChapterPage:
        self._rate_limiter.acquire()
        html = self._http.get(url, headers={
            "Cookie": "night=0",
            "Referer": DOMAIN,
        })
        soup = BeautifulSoup(html, "lxml")

        current_page_id = _extract_page_id(url)

        title = None
        if "_" not in url:
            t = _first_of(soup, "#atitle", "#mlfy_main_text h1")
            if t:
                title = t.get_text(strip=True)

        content = None
        for sel in ["#acontent", ".contente", "#TextContent", ".TextContent"]:
            content = soup.select_one(sel)
            if content:
                break

        if content is None:
            raise RuntimeError(f"Cannot find content on page: {url}")

        prev_page = None
        next_page = None
        prev_chapter = None
        next_chapter = None

        nav_match = re.search(r"url_previous:'(.*?)',url_next:'(.*?)'", html)
        prev_url = nav_match.group(1) if nav_match else None
        next_url = nav_match.group(2) if nav_match else None

        mlfy_page = soup.select_one(".mlfy_page")
        if mlfy_page:
            links = mlfy_page.select("a")
            for link in links:
                text = link.get_text(strip=True)
                href = link.get("href", "")
                if not href:
                    continue
                full_url = f"{DOMAIN}{href}" if href.startswith("/") else href
                link_page_id = _extract_page_id(full_url)

                if text in ("上一页", "上一頁"):
                    if link_page_id and link_page_id.startswith(str(current_page_id or "")):
                        prev_page = full_url
                    else:
                        prev_chapter = full_url
                elif text in ("下一页", "下一頁"):
                    if link_page_id and link_page_id.startswith(str(current_page_id or "")):
                        next_page = full_url
                    else:
                        next_chapter = full_url

        if not prev_page and not next_page:
            footlink = soup.select_one("#footlink")
            if footlink:
                links = footlink.select("a")
                if len(links) >= 2:
                    prev_text = links[0].get_text(strip=True)
                    next_text = links[-1].get_text(strip=True)
                    if prev_text in ("上一页", "上一頁") and prev_url:
                        prev_page = DOMAIN + prev_url
                    elif prev_url:
                        prev_chapter = DOMAIN + prev_url
                    if next_text in ("下一页", "下一頁") and next_url:
                        next_page = DOMAIN + next_url
                    elif next_url:
                        next_chapter = DOMAIN + next_url

        remove_elements(content.select("div"))
        remove_elements(content.select("ins"))
        remove_elements(content.select("figure"))
        remove_elements(content.select("fig"))
        remove_elements(content.select("br"))
        remove_elements(content.select("script"))
        remove_elements(content.select(".tp"))
        remove_elements(content.select(".bd"))
        remove_elements(content.select(".dag"))

        ch_id_match = CHAPTER_ID_RE.search(html)
        if ch_id_match:
            chapter_id = int(ch_id_match.group(1))
            params = self._chapterlog.get_shuffle_params(soup, chapter_id)
            if params:
                p_elements = [
                    el for el in content.children
                    if isinstance(el, Tag) and el.name == "p" and el.get_text(strip=True)
                ]
                if p_elements:
                    from utils.chapterlog import ShuffleParams
                    seed = chapter_id * DEFAULT_SEED_MULTIPLIER + DEFAULT_SEED_OFFSET
                    full_params = ShuffleParams(
                        fixed_length=params.fixed_length,
                        seed=seed,
                        a=params.a,
                        c=params.c,
                        mod=params.mod,
                    )
                    reordered = reverse_shuffle(p_elements, full_params)
                    for p in p_elements:
                        p.extract()
                    for p in reordered:
                        content.append(p)

        return self._ChapterPage(
            title=title,
            contents=[el for el in content.children if isinstance(el, Tag)],
            prev_page_url=prev_page,
            next_page_url=next_page,
            prev_chapter_url=prev_chapter,
            next_chapter_url=next_chapter,
        )

    @staticmethod
    def _fix_image_srcs(element: Tag) -> None:
        for img in element.select("img"):
            src = img.get("data-original") or img.get("data-src") or img.get("src")
            if src:
                if "<" in src:
                    img.decompose()
                    continue
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = DOMAIN + src
                elif not src.startswith("http"):
                    src = DOMAIN + "/" + src
                img["src"] = src
            for attr in list(img.attrs.keys()):
                if attr not in ("src", "alt", "class"):
                    del img[attr]

    def download_image(self, src: str) -> bytes:
        if src.startswith("data:image"):
            import base64
            return base64.b64decode(src.split(",")[1])
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = DOMAIN + src
        elif not src.startswith("http"):
            src = DOMAIN + "/" + src
        src = src.replace("https://https://", "https://")
        self._img_rate_limiter.acquire()
        return self._http.get_bytes(src, headers={
            "Referer": DOMAIN,
        })
