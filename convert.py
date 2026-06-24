#!/usr/bin/env python3
"""
Convert enwiktionary XML dump to StarDict dictionary format.

Usage:
    # Download and convert in one step:
    python convert.py --download --output dict-en-en.zip

    # Convert from a local dump:
    python convert.py --dump enwiktionary-20260601-pages-articles.xml.bz2 --output dict-en-en.zip

    # Test with a small sample:
    python convert.py --sample --output dict-en-en.zip

Output: a StarDict-compatible .zip containing:
    - dict-en-en.ifo    (metadata)
    - dict-en-en.idx    (binary word index)
    - dict-en-en.dict   (definition data, gzip-compressed as .dict.dz)
"""

import argparse
import bz2
import gzip
import io
import os
import struct
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen

DICT_NAME = "English (Wiktionary)"
DICT_LANG = "en"
STAR_DICT_VERSION = "3.0.0"

WIKTIONARY_DUMP_URL = (
    "https://dumps.wikimedia.org/enwiktionary/latest/"
    "enwiktionary-latest-pages-articles.xml.bz2"
)

# Sections we want under ==English== in order of importance
POS_SECTIONS = [
    "Noun", "Verb", "Adjective", "Adverb", "Pronoun",
    "Preposition", "Conjunction", "Interjection", "Article",
    "Determiner", "Numeral", "Particle", "Contraction",
    "Proper noun", "Prefix", "Suffix", "Combining form",
    "Idiom", "Phrase", "Proverb", "Initialism", "Abbreviation",
]

# Wiktionary namespace 0 = main entries
NS = "{http://www.mediawiki.org/xml/export-0.11/}"
NS_MAIN = "0"


def tag(name: str) -> str:
    """Return fully qualified XML tag with namespace."""
    return f"{NS}{name}"


def clean_wikitext(text: str) -> str:
    """Strip MediaWiki markup, keep readable definition text."""
    result = text
    # Remove template invocations {{...|...}}
    depth = 0
    cleaned = []
    for ch in result:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(depth - 1, 0)
        elif depth == 0:
            cleaned.append(ch)
    result = "".join(cleaned)

    # Remove [[target|display]] -> display; [[target]] -> target
    result = result.replace("[[", "").replace("]]", "")

    # Remove URL markup [https://... text] -> text
    import re
    result = re.sub(r'\[(?:https?|ftp)://\S+\s+(.+?)\]', r'\1', result)
    result = re.sub(r'\[(?:https?|ftp)://\S+\]', '', result)

    # Remove '''bold''' and ''italic''
    result = result.replace("'''", "").replace("''", "")

    # Remove <ref>...</ref> and other inline HTML tags
    result = re.sub(r'<ref[^>]*>.*?</ref>', '', result, flags=re.DOTALL)
    result = re.sub(r'<[^>]+>', '', result)

    # Remove &nbsp; etc
    result = result.replace("&nbsp;", " ")

    # Collapse whitespace
    result = re.sub(r'\s+', ' ', result).strip()

    # Skip empty, references-only, or non-definition lines
    if not result or result.startswith("(") or result.startswith("&#"):
        return ""

    return result


def extract_english_definitions(wikitext: str) -> list[str]:
    """
    Extract English definition lines from wikitext.

    Looks for ==English== section, then POS subsections (===Noun=== etc),
    then numbered definition lines starting with '#'.

    Returns a list of cleaned definition strings.
    """
    if "==English==" not in wikitext:
        return []

    # Split into =level= sections
    lines = wikitext.split("\n")

    # Find content after ==English==
    in_english = False
    english_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "==English==":
            in_english = True
            continue
        if in_english:
            # Stop at next top-level language section
            if stripped.startswith("==") and not stripped.startswith("==="):
                break
            english_lines.append(line)

    definitions: list[str] = []
    current_pos = "General"

    for line in english_lines:
        stripped = line.strip()

        # Track POS subsection (===Noun===, ===Verb=== etc)
        if stripped.startswith("===") and stripped.endswith("==="):
            pos = stripped.strip("= ").split("|")[0].split("<")[0].strip()
            current_pos = pos
            continue

        # Extract numbered definition lines only (skip examples starting with #:)
        if stripped.startswith("#") and not stripped.startswith("#:"):
            def_text = stripped.lstrip("#").strip()
            if not def_text:
                continue
            cleaned = clean_wikitext(def_text)
            if cleaned:
                definitions.append(f"({current_pos}) {cleaned}")

    return definitions


def create_stardict(entries: list[tuple[str, str]]) -> tuple[bytes, bytes, bytes]:
    """
    Create StarDict binary format from entries.

    entries: list of (word, definition) tuples, sorted alphabetically.

    Returns (ifo_content, idx_data, dict_data) as bytes.
    """
    # Sort entries by word (case-insensitive for lookup compatibility)
    entries.sort(key=lambda e: e[0].lower())

    # Build .dict data (definitions concatenated)
    dict_entries: list[tuple[str, int, int]] = []  # word, offset, size
    dict_data = bytearray()

    for word, definition in entries:
        offset = len(dict_data)
        def_bytes = definition.encode("utf-8")
        dict_data.extend(def_bytes)
        dict_entries.append((word, offset, len(def_bytes)))

    # Build .idx (binary index)
    idx_data = bytearray()
    for word, offset, size in dict_entries:
        word_bytes = word.encode("utf-8")
        idx_data.extend(word_bytes)
        idx_data.append(0)  # null terminator
        # offset: 4 bytes big-endian uint32
        idx_data.extend(struct.pack(">I", offset))
        # size: 4 bytes big-endian uint32
        idx_data.extend(struct.pack(">I", size))

    # Build .ifo (metadata)
    ifo_lines = [
        f"StarDict={STAR_DICT_VERSION}",
        f"bookname={DICT_NAME}",
        f"wordcount={len(entries)}",
        f"idxfilesize={len(idx_data)}",
        f"author=Wiktionary contributors",
        f"description=English definitions extracted from Wiktionary (CC BY-SA 3.0)",
        f"date={__import__('datetime').date.today().isoformat()}",
        f"sametypesequence=m",
        f"lang={DICT_LANG}",
    ]
    ifo_content = "\n".join(ifo_lines) + "\n"

    # .dict.dz = gzip-compressed dict data
    import gzip
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf) as gz:
        gz.write(bytes(dict_data))
    dict_dz = buf.getvalue()

    return (ifo_content.encode("utf-8"), bytes(idx_data), dict_dz)


def create_zip(ifo: bytes, idx: bytes, dict_dz: bytes, output_path: str):
    """Create a ZIP file containing the StarDict files."""
    import zipfile
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("dict-en-en.ifo", ifo)
        zf.writestr("dict-en-en.idx", idx)
        zf.writestr("dict-en-en.dict.dz", dict_dz)
    print(f"Created {output_path}")
    print(f"  Size: {os.path.getsize(output_path) / 1024 / 1024:.1f} MB")


def parse_page(
    title: str,
    ns: str,
    text: str,
) -> tuple[str, list[str]] | None:
    """Parse a single Wiktionary page. Returns (word, definitions) or None."""
    if ns != NS_MAIN:
        return None
    if "==English==" not in text:
        return None

    definitions = extract_english_definitions(text)
    if not definitions:
        return None

    return (title, definitions)


def process_dump(
    dump_path: str,
    output_path: str,
    max_pages: int | None = None,
    progress_interval: int = 10000,
):
    """
    Process a Wiktionary XML dump and generate StarDict files.

    Uses iterparse for streaming — memory efficient even for 5GB+ files.
    """
    entries_dict: dict[str, list[str]] = {}
    page_count = 0
    english_count = 0
    open_file = None

    try:
        if dump_path.endswith(".bz2"):
            open_file = bz2.open(dump_path, "rb")
        else:
            open_file = open(dump_path, "rb")

        context = ET.iterparse(open_file, events=("end",))
        event, root = next(context)  # Get the root <mediawiki> element

        for event, elem in context:
            if elem.tag == tag("page"):
                page_count += 1
                title_el = elem.find(tag("title"))
                ns_el = elem.find(tag("ns"))
                text_el = elem.find(f"{tag('revision')}/{tag('text')}")

                if title_el is not None and text_el is not None and text_el.text:
                    ns = ns_el.text if ns_el is not None else "0"
                    result = parse_page(title_el.text, ns, text_el.text)
                    if result:
                        word, definitions = result
                        if word not in entries_dict:
                            entries_dict[word] = []
                        entries_dict[word].extend(definitions)
                        english_count += 1

                # Free processed pages to keep memory bounded
                root.clear()

                if progress_interval and page_count % progress_interval == 0:
                    print(
                        f"  Processed {page_count:,} pages, "
                        f"{english_count:,} English entries found",
                        end="\r",
                    )

                if max_pages and page_count >= max_pages:
                    break

    finally:
        if open_file:
            open_file.close()

    print()
    print(f"Total pages processed: {page_count:,}")
    print(f"English entries found: {english_count:,}")
    print(f"Total word-definition pairs: {sum(len(v) for v in entries_dict.values()):,}")

    if not entries_dict:
        print("ERROR: No English entries found!", file=sys.stderr)
        sys.exit(1)

    # Convert dict to list of (word, joined_definitions)
    entries = [(word, "  ".join(defs)) for word, defs in entries_dict.items()]
    print(f"Unique words: {len(entries):,}")

    ifo, idx, dict_dz = create_stardict(entries)
    create_zip(ifo, idx, dict_dz, output_path)


def create_sample_dump(path: str):
    """Create a small sample XML for testing."""
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xsi:schemaLocation="http://www.mediawiki.org/xml/export-0.11/
           http://www.mediawiki.org/xml/export-0.11.xsd"
           version="0.11" lang="en">
  <siteinfo>
    <sitename>Wiktionary</sitename>
    <base>https://en.wiktionary.org</base>
    <case>first-letter</case>
  </siteinfo>
  <page>
    <title>hello</title>
    <ns>0</ns>
    <revision>
      <text>{{wiktionary|hello}}
==English==
===Interjection===
# Used as a greeting.
#: '''''Hello''', how are you?''
===Noun===
# "Hello" or "hello" — a greeting.
#: ''We gave a quick '''hello''' to the neighbours.''
===Verb===
# To greet with "hello".
      </text>
    </revision>
  </page>
  <page>
    <title>world</title>
    <ns>0</ns>
    <revision>
      <text>{{wiktionary|world}}
==English==
===Noun===
# The [[Earth]], especially as a planet.
#: ''The '''world''' is round.''
# A particular sphere of activity or interest.
#: ''the business '''world'''''
===Adjective===
# Encompassing all of the world.
      </text>
    </revision>
  </page>
  <page>
    <title>book</title>
    <ns>0</ns>
    <revision>
      <text>{{wiktionary|book}}
==English==
===Noun===
# A collection of sheets of paper bound together.
#: ''I'm reading a '''book'''.''
===Verb===
# To reserve something.
#: ''I'd like to '''book''' a table.''
      </text>
    </revision>
  </page>
</mediawiki>"""
    with bz2.open(path, "wb") as f:
        f.write(sample_xml.encode("utf-8"))
    print(f"Created sample dump: {path}")


def download_dump(output_path: str):
    """Download enwiktionary dump."""
    print(f"Downloading from {WIKTIONARY_DUMP_URL}...")
    import shutil
    with urlopen(WIKTIONARY_DUMP_URL) as response:
        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        with open(output_path, "wb") as f:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"  Downloading: {pct}% ({downloaded/1024/1024:.0f}MB)", end="\r")
    print(f"\nDownloaded to {output_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", help="Path to enwiktionary XML dump (.bz2)")
    parser.add_argument("--output", default="dict-en-en.zip", help="Output ZIP path")
    parser.add_argument("--download", action="store_true", help="Download the latest dump")
    parser.add_argument("--sample", action="store_true", help="Use a small sample for testing")
    parser.add_argument("--max-pages", type=int, help="Stop after N pages (for testing)")
    args = parser.parse_args()

    if args.sample:
        sample_path = "/tmp/enwiktionary-sample.xml.bz2"
        create_sample_dump(sample_path)
        process_dump(sample_path, args.output, progress_interval=1)
        return

    dump_path = args.dump
    if args.download:
        if not dump_path:
            dump_path = "/tmp/enwiktionary-latest-pages-articles.xml.bz2"
        download_dump(dump_path)

    if not dump_path:
        print("ERROR: Provide --dump, --download, or --sample", file=sys.stderr)
        sys.exit(1)

    process_dump(dump_path, args.output, max_pages=args.max_pages)


if __name__ == "__main__":
    main()
