# 轻小说打包器 (Python)

将哔哩轻小说 (linovelib.com) 的小说打包为 EPUB 格式。

基于 [Montaro2017/bili_novel_packer](https://github.com/Montaro2017/bili_novel_packer) 的思路用 Python 重写，使用 `curl_cffi` 模拟 Chrome TLS 指纹绕过 Cloudflare 反爬。

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

双击 `run.bat` 一键启动。

## 打包 EXE

```
双击 compile.bat
→ build/bili_novel_packer.exe
```

## 与原 Dart 版的区别

- `curl_cffi` 替代 `package:http`，能过 Cloudflare JS Challenge
- 抓取 PC 版页面 (linovelib.com)，内容完整不截断
- 无需解密 secret map / 字体映射
- 跨平台

## License

CC BY-NC 4.0 — 个人非商业使用
