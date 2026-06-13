import io
import uuid
from pathlib import Path
from typing import Optional
from PIL import Image as PILImage
from bs4 import BeautifulSoup, Tag
from ebooklib import epub

from sources.bili_novel import BiliNovelSource, Novel, Volume, Chapter, Catalog
from utils.html_utils import wrap_duokan_image


CHAPTER_TITLE_CSS = """
h1.chapter-title {
    text-align: center;
    font-size: 1.5em;
    margin: 1em 0;
    font-weight: bold;
}
"""

DUOKAN_IMAGE_CSS = """
.duokan-image-single {
    text-align: center;
    margin: 0.5em 0;
}
.duokan-image-single img {
    max-width: 100%;
    height: auto;
}
"""


class EpubPacker:
    def __init__(self, source: BiliNovelSource):
        self._source = source
        self._image_map: dict[str, tuple[str, bytes]] = {}

    def pack(
        self,
        catalog: Catalog,
        volumes: list[Volume],
        output_dir: str = ".",
        combine: bool = False,
        add_chapter_title: bool = True,
    ) -> list[str]:
        output_paths = []

        if combine:
            all_chapters = []
            for vol in volumes:
                all_chapters.extend(vol.chapters)
            path = self._pack_epub(
                catalog.novel,
                all_chapters,
                output_dir,
                f"{catalog.novel.title}.epub",
                add_chapter_title,
            )
            output_paths.append(path)
        else:
            for vol in volumes:
                path = self._pack_epub(
                    catalog.novel,
                    vol.chapters,
                    output_dir,
                    f"{vol.name}.epub" if vol.name else f"{catalog.novel.title}.epub",
                    add_chapter_title,
                )
                output_paths.append(path)

        return output_paths

    def _pack_epub(
        self,
        novel: Novel,
        chapters: list[Chapter],
        output_dir: str,
        filename: str,
        add_chapter_title: bool,
    ) -> str:
        self._image_map.clear()
        book = epub.EpubBook()
        book.set_identifier(f"bili-novel-{novel.id}-{uuid.uuid4().hex[:8]}")
        book.set_title(novel.title)
        book.set_language("zh")
        book.add_author(novel.author or "Unknown")

        default_css = epub.EpubItem(
            uid="default_css",
            file_name="style/default.css",
            media_type="text/css",
            content=(CHAPTER_TITLE_CSS + DUOKAN_IMAGE_CSS).encode("utf-8"),
        )
        book.add_item(default_css)

        cover_data = None
        cover_ext = ".jpg"
        if novel.cover_url:
            try:
                cover_data = self._source.download_image(novel.cover_url)
                cover_ext = self._guess_ext(novel.cover_url)
            except Exception as e:
                print(f"  [warn] Failed to download cover: {e}")

        epub_chapters = []
        spine = ["nav"]

        for i, chapter in enumerate(chapters):
            print(f"  [{i+1}/{len(chapters)}] {chapter.name}")
            try:
                html = self._source.get_chapter_html(chapter)
            except Exception as e:
                print(f"  [error] {chapter.name}: {e}")
                html = f"<p>Error: {e}</p>"

            soup = BeautifulSoup(html, "lxml")
            root = soup.select_one("body") or soup.select_one("div") or soup

            if root is None:
                content_html = html
            else:
                if add_chapter_title:
                    h1 = soup.new_tag("h1")
                    h1["class"] = "chapter-title"
                    h1.string = chapter.name
                    root.insert(0, h1)

                wrap_duokan_image(root)
                self._replace_images(soup)
                content_html = root.decode_contents()

            epub_chapter = epub.EpubHtml(
                title=chapter.name,
                file_name=f"chapter_{i:04d}.xhtml",
                lang="zh",
            )
            epub_chapter.content = f"""<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh">
<head><title>{chapter.name}</title><link rel="stylesheet" type="text/css" href="style/default.css"/></head>
<body>{content_html}</body>
</html>"""

            book.add_item(epub_chapter)
            epub_chapters.append(epub_chapter)
            spine.append(epub_chapter)

        self._embed_images(book)

        book.toc = tuple(epub_chapters)
        book.spine = spine
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        if cover_data:
            try:
                book.set_cover(f"images/cover{cover_ext}", cover_data, create_page=False)
            except Exception as e:
                print(f"  [warn] Failed to set cover: {e}")

        safe_name = self._safe_name(filename)
        out_path = str(Path(output_dir) / safe_name)
        epub.write_epub(out_path, book, options={"epub3_pages": False})
        print(f"  -> {out_path}")
        return out_path

    def _replace_images(self, soup: BeautifulSoup) -> None:
        for i, img in enumerate(soup.select("img")):
            src = img.get("src", "")
            if not src:
                continue
            if src.startswith("data:"):
                continue
            ext = self._guess_ext(src)
            img_name = f"img_{i:05d}{ext}"
            img["src"] = f"images/{img_name}"
            self._image_map[img_name] = (src, b"")

    def _embed_images(self, book: epub.EpubBook) -> None:
        for name, (src, _) in self._image_map.items():
            try:
                data = self._source.download_image(src)
                ext = self._guess_ext(name)
                img = epub.EpubImage()
                img.file_name = f"images/{name}"
                img.media_type = self._mime_type(ext)
                img.content = data
                book.add_item(img)
            except Exception as e:
                print(f"  [warn] Failed to download image {src}: {e}")

    @staticmethod
    def _guess_ext(path: str) -> str:
        lower = path.lower()
        if ".jpg" in lower or ".jpeg" in lower:
            return ".jpg"
        if ".png" in lower:
            return ".png"
        if ".gif" in lower:
            return ".gif"
        if ".webp" in lower:
            return ".webp"
        return ".jpg"

    @staticmethod
    def _mime_type(ext: str) -> str:
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(ext, "image/jpeg")

    @staticmethod
    def _safe_name(name: str) -> str:
        invalid = '<>:"/\\|?*'
        for ch in invalid:
            name = name.replace(ch, "_")
        return name.strip()
