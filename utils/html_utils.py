import re
from bs4 import Tag

_PLACEHOLDER = "（內容加載失敗！請刷新或更換瀏覽器）"
_PLACEHOLDER_FULLWIDTH = "\uff08\u5185\u5bb9\u52a0\u8f7d\u5931\u8d25\uff01\u8bf7\u5237\u65b0\u6216\u66f4\u6362\u700f\u89c8\u5668\uff09"


def remove_elements(elements: list[Tag]) -> None:
    for el in elements:
        el.decompose()


def remove_line_breaks(element: Tag) -> None:
    for child in element.find_all(string=True):
        if child.string:
            child.string.replace_with(child.string.replace("\n", ""))


def remove_load_failed_placeholder(element: Tag) -> None:
    text = element.get_text()
    if _PLACEHOLDER in text or _PLACEHOLDER_FULLWIDTH in text:
        full = text
        full = full.replace(_PLACEHOLDER, "")
        full = full.replace(_PLACEHOLDER_FULLWIDTH, "")
        full = re.sub(r"……\.{0,3}\s*", "", full)
        full = re.sub(r"…\.{0,3}\s*", "", full)
        if full.strip():
            element.string = full.strip()
        else:
            element.decompose()
            return

    for child in element.children:
        if isinstance(child, Tag):
            remove_load_failed_placeholder(child)


def wrap_duokan_image(element: Tag) -> None:
    for img in element.find_all("img"):
        div = Tag(name="div")
        div["class"] = "duokan-image-single"
        img.wrap(div)
