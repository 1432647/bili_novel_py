"""轻小说打包器 - 将支持的轻小说网站中的小说打包成 EPUB 格式"""
import sys
from pathlib import Path

from sources.bili_novel import BiliNovelSource, Novel, Volume, Catalog
from epub.packer import EpubPacker


def main():
    print("欢迎使用轻小说打包器!")
    print("当前版本: 0.3.0 (Python rewrite)")
    print("如遇报错请先查看能否正常访问输入网址")
    print()

    url = input("请输入URL (支持哔哩轻小说): ").strip().split()[0]
    if not url:
        print("URL 不能为空")
        return

    source = BiliNovelSource()
    if not source.supports(url):
        print(f"不支持的URL: {url}")
        return

    print("\n正在加载数据...")
    novel = source.get_novel(url)
    print(f"\n{novel.title}")
    print(f"作者: {novel.author}")
    print(f"状态: {novel.status}")
    if novel.tags:
        print(f"标签: {', '.join(novel.tags)}")
    if novel.description:
        print(f"\n{novel.description}")
    print()

    catalog = source.get_catalog(novel)
    print(f"共 {len(catalog.volumes)} 卷\n")

    for i, vol in enumerate(catalog.volumes):
        print(f"  [{i + 1}] {vol.name} ({len(vol.chapters)}章)")

    print("  [0] 选择全部")
    print()
    selection = input("请选择需要下载的分卷 (如 1-3 或 2,5): ").strip()

    if not selection or selection == "0":
        volumes = catalog.volumes
    else:
        volumes = _parse_selection(selection, catalog.volumes)

    if not volumes:
        print("未选择任何分卷")
        return

    combine = False
    if len(volumes) > 1:
        combine_ans = input("\n是否合并选择的分卷为一个文件? (y/n): ").strip().lower()
        combine = combine_ans == "y"

    add_title_ans = input("\n是否在每章开头添加章节标题? (y/n): ").strip().lower()
    add_title = add_title_ans != "n"

    print(f"\n开始打包 {len(volumes)} 个分卷...")

    packer = EpubPacker(source)

    base_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
    output_dir = base_dir / novel.title
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        paths = packer.pack(
            catalog,
            volumes,
            output_dir=output_dir,
            combine=combine,
            add_chapter_title=add_title,
        )
        print(f"\n打包完成! 共生成 {len(paths)} 个文件:")
        for p in paths:
            print(f"  {p}")
    except Exception as e:
        print(f"\n出错: {e}")
        import traceback
        traceback.print_exc()

    print("\n按回车键退出.")
    input()


def _parse_selection(selection: str, volumes: list[Volume]) -> list[Volume]:
    result = []
    selection = selection.replace("，", ",").replace(" ", ",")
    for part in selection.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                start, end = int(a.strip()), int(b.strip())
                if start > end:
                    start, end = end, start
                for i in range(start - 1, end):
                    if 0 <= i < len(volumes):
                        result.append(volumes[i])
            except ValueError:
                pass
        else:
            try:
                i = int(part) - 1
                if 0 <= i < len(volumes):
                    result.append(volumes[i])
            except ValueError:
                pass
    return result


if __name__ == "__main__":
    main()
