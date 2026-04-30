"""
微信 HTML 格式转换服务
业务逻辑完全来自 html_to_wechat_html.py，完全保留
"""
from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ALLOWED_TAGS = {
    "a", "article", "blockquote", "br", "code", "div", "em",
    "figcaption", "figure", "h1", "h2", "h3", "h4", "hr",
    "img", "li", "ol", "p", "pre", "section", "span",
    "strong", "sub", "sup", "u", "ul",
}

ALLOWED_ATTRS = {
    "a": {"href", "style", "title"},
    "article": {"style"},
    "blockquote": {"style"},
    "br": set(),
    "code": {"style"},
    "div": {"style"},
    "em": {"style"},
    "figcaption": {"style"},
    "figure": {"style"},
    "h1": {"style"},
    "h2": {"style"},
    "h3": {"style"},
    "h4": {"style"},
    "hr": {"style"},
    "img": {"src", "style", "alt", "title", "data-src"},
    "li": {"style"},
    "ol": {"style"},
    "p": {"style"},
    "pre": {"style"},
    "section": {"style"},
    "span": {"style"},
    "strong": {"style"},
    "sub": {"style"},
    "sup": {"style"},
    "u": {"style"},
    "ul": {"style"},
}

ALLOWED_CSS = {
    "background", "background-color", "border", "border-bottom",
    "border-left", "border-radius", "border-top", "color", "display",
    "font-family", "font-size", "font-style", "font-weight", "height",
    "letter-spacing", "line-height", "list-style-type", "margin",
    "margin-bottom", "margin-left", "margin-right", "margin-top",
    "max-width", "min-height", "padding", "padding-bottom",
    "padding-left", "padding-right", "padding-top", "text-align",
    "text-decoration", "text-indent", "vertical-align", "white-space",
    "width", "word-break",
}

DROP_TAGS_WITH_CONTENT = {
    "script", "style", "iframe", "object", "embed", "form", "input", "button"
}


def _ensure_bs4():
    try:
        return importlib.import_module("bs4")
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "beautifulsoup4"], check=True)
        return importlib.import_module("bs4")


def _ensure_markdown():
    try:
        return importlib.import_module("markdown")
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "markdown"], check=True)
        return importlib.import_module("markdown")


def _rgb_to_hex(value: str) -> str:
    def replace(match: re.Match) -> str:
        r = max(0, min(255, int(match.group(1))))
        g = max(0, min(255, int(match.group(2))))
        b = max(0, min(255, int(match.group(3))))
        return f"#{r:02x}{g:02x}{b:02x}"
    return re.sub(
        r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)",
        replace, value, flags=re.I,
    )


def _normalize_css_value(value: str) -> str:
    value = _rgb_to_hex(value.strip())
    return re.sub(r"\s+", " ", value)


def _parse_inline_style(style_text: str) -> dict[str, str]:
    styles: dict[str, str] = {}
    for part in style_text.split(";"):
        if ":" not in part:
            continue
        prop, value = part.split(":", 1)
        prop = prop.strip().lower()
        value = _normalize_css_value(value)
        if prop and value and prop in ALLOWED_CSS:
            styles[prop] = value
    return styles


def _style_dict_to_text(style_dict: dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in style_dict.items())


def _merge_style_text(*style_texts: str) -> str:
    merged: dict[str, str] = {}
    for style_text in style_texts:
        if style_text:
            merged.update(_parse_inline_style(style_text))
    return _style_dict_to_text(merged)


def _parse_style_rules(style_blocks: Iterable[str]) -> dict[str, str]:
    rules: dict[str, str] = {}
    block_text = "\n".join(style_blocks)
    for selector, css_body in re.findall(r"([^{]+)\{([^}]*)\}", block_text, flags=re.S):
        selector = selector.strip()
        css_body = css_body.strip()
        if not selector or not css_body:
            continue
        selectors = [s.strip() for s in selector.split(",")]
        for single in selectors:
            if not single or " " in single or ":" in single or "#" in single:
                continue
            class_names = re.findall(r"\.([A-Za-z0-9_-]+)", single)
            if not class_names:
                continue
            normalized = _style_dict_to_text(_parse_inline_style(css_body))
            for class_name in class_names:
                existing = rules.get(class_name, "")
                rules[class_name] = _merge_style_text(existing, normalized)
    return rules


def _markdown_to_html(markdown_text: str) -> str:
    md = _ensure_markdown()
    return md.markdown(
        markdown_text,
        extensions=["extra", "sane_lists"],
        output_format="html5",
    )


def sanitize_wechat_html(html_text: str) -> str:
    """完整保留 html_to_wechat_html.py 的 sanitize_wechat_html 逻辑"""
    bs4 = _ensure_bs4()
    BeautifulSoup = bs4.BeautifulSoup
    Comment = bs4.Comment

    soup = BeautifulSoup(html_text, "html.parser")

    style_blocks = [tag.get_text("\n", strip=True) for tag in soup.find_all("style")]
    class_style_rules = _parse_style_rules(style_blocks)

    for tag_name in DROP_TAGS_WITH_CONTENT:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    for tag in list(soup.find_all(True)):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue

        class_names = tag.get("class", []) or []
        class_style = ""
        for class_name in class_names:
            class_style = _merge_style_text(class_style, class_style_rules.get(class_name, ""))

        current_style = tag.get("style", "")
        merged_style = _merge_style_text(class_style, current_style)

        allowed_attrs = ALLOWED_ATTRS.get(tag.name, set())
        for attr_name in list(tag.attrs.keys()):
            if attr_name == "class":
                del tag.attrs[attr_name]
                continue
            if attr_name not in allowed_attrs:
                del tag.attrs[attr_name]

        if merged_style:
            tag["style"] = merged_style
        elif "style" in tag.attrs:
            del tag.attrs["style"]

        if tag.name == "a":
            href = (tag.get("href") or "").strip()
            if not href:
                tag.unwrap()
                continue
            if not re.match(r"^(https?:|weixin://)", href, flags=re.I):
                del tag.attrs["href"]

        if tag.name == "img":
            src = (tag.get("src") or tag.get("data-src") or "").strip()
            if not src:
                tag.decompose()
                continue
            if tag.get("data-src") and "src" not in tag.attrs:
                tag["src"] = tag["data-src"]
            if "data-src" in tag.attrs:
                del tag.attrs["data-src"]
            if "style" not in tag.attrs:
                tag["style"] = (
                    "max-width: 100%; height: auto; display: block; margin: 12px auto"
                )
            else:
                tag["style"] = _merge_style_text(
                    tag["style"],
                    "max-width: 100%; height: auto; display: block; margin: 12px auto",
                )

    root = soup.body if soup.body else soup
    output_parts: list[str] = []
    for child in root.contents:
        rendered = str(child).strip()
        if rendered:
            output_parts.append(rendered)
    return "\n".join(output_parts).strip()


def convert_to_wechat_html(input_text: str, is_markdown: bool = False) -> str:
    """将文本（HTML 或 Markdown）转换为微信公众号格式 HTML"""
    if is_markdown:
        input_text = _markdown_to_html(input_text)
    return sanitize_wechat_html(input_text)


def convert_file_to_wechat_html(input_path: Path, output_path: Path) -> str:
    """从文件读取并转换，保存结果，返回 HTML 字符串"""
    text = input_path.read_text(encoding="utf-8")
    is_markdown = input_path.suffix.lower() in {".md", ".markdown"}
    result = convert_to_wechat_html(text, is_markdown=is_markdown)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    return result
