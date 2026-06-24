# wiktionary-stardict

[![Build English Dictionary](https://github.com/sapienskid/wiktionary-stardict/actions/workflows/build.yml/badge.svg)](https://github.com/sapienskid/wiktionary-stardict/actions/workflows/build.yml)

Convert Wiktionary XML dumps to [StarDict](https://en.wikipedia.org/wiki/StarDict) dictionary format.

## Pre-built dictionary

The latest English dictionary is available as a [GitHub Release](https://github.com/sapienskid/wiktionary-stardict/releases/tag/en-latest):

```
https://github.com/sapienskid/wiktionary-stardict/releases/download/en-latest/dict-en-en.zip
```

Updated monthly via CI. Fast downloads through GitHub's CDN.

## Usage

```bash
# Test with a small sample:
python3 convert.py --sample --output dict-en-en.zip

# Full English dictionary (requires the full enwiktionary dump, ~1.5GB compressed):
python3 convert.py --download --output dict-en-en.zip

# Or use a local dump:
python3 convert.py --dump enwiktionary-20260601-pages-articles.xml.bz2 --output dict-en-en.zip
```

## Output

Creates a `.zip` file containing three StarDict files:

| File | Description |
|---|---|
| `dict-en-en.ifo` | Metadata (word count, index size, etc.) |
| `dict-en-en.idx` | Binary word index — maps each word to its offset in the dict file |
| `dict-en-en.dict.dz` | Gzip-compressed definitions |

## How it works

1. Downloads/reads the [enwiktionary XML dump](https://dumps.wikimedia.org/enwiktionary/)
2. Streams through pages (memory-efficient, handles 5GB+ files)
3. For each page with `==English==` section:
   - Extracts `===POS===` subsections (Noun, Verb, Adjective, etc.)
   - Picks numbered definition lines (`# ...`)
   - Cleans MediaWiki markup
4. Groups definitions by word and generates StarDict binary format
5. Outputs a standard StarDict `.zip` compatible with any StarDict-based reader

## Automated builds

The dictionary is rebuilt monthly via [GitHub Actions](.github/workflows/build.yml).
The latest build is always available at the `en-latest` release tag.

## License

- **Script code**: CC BY-SA 4.0
- **Dictionary data**: extracted from [Wiktionary](https://en.wiktionary.org), available under CC BY-SA 3.0
