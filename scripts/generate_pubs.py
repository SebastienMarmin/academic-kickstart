#!/usr/bin/env python3

import sys
import os
import re
import argparse
from argparse import RawTextHelpFormatter
from pathlib import Path
import calendar
from datetime import datetime
from glob import glob
import tempfile
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.customization import convert_to_unicode
import shutil

import collections
from collections import defaultdict
from pprint import pprint

# Map BibTeX to Academic publication types.
PUB_TYPES = {
    'article': 2,
    'book': 5,
    'inbook': 6,
    'incollection': 6,
    'inproceedings': 1,
    'manual': 4,
    'mastersthesis': 7,
    'misc': 0,
    'phdthesis': 7,
    'proceedings': 0,
    'techreport': 4,
    'unpublished': 3,
    'patent': 8
}



def slugify(s, lower=True):
    bad_symbols = ('.', '_', ':')  # Symbols to replace with hyphen delimiter.
    delimiter = '-'
    good_symbols = (delimiter,)  # Symbols to keep.
    for r in bad_symbols:
        s = s.replace(r, delimiter)

    s = re.sub(r'(\D+)(\d+)', r'\1\-\2', s)  # Delimit non-number, number.
    s = re.sub(r'(\d+)(\D+)', r'\1\-\2', s)  # Delimit number, non-number.
    s = re.sub(r'((?<=[a-z])[A-Z]|(?<!\A)[A-Z](?=[a-z]))', r'\-\1', s)  # Delimit camelcase.
    s = ''.join(c for c in s if c.isalnum() or c in good_symbols).strip()  # Strip non-alphanumeric and non-hyphen.
    s = re.sub('\-+', '-', s)  # Remove consecutive hyphens.

    if lower:
        s = s.lower()
    return s


def clean_bibtex_authors(author_str):
    """Convert author names to `firstname(s) lastname` format."""
    authors = []
    for s in author_str:
        s = s.strip()
        if len(s) < 1:
            continue
        if ',' in s:
            split_names = s.split(',', 1)
            last_name = split_names[0].strip()
            first_names = [i.strip() for i in split_names[1].split()]
        else:
            split_names = s.split()
            last_name = split_names.pop()
            first_names = [i.replace('.', '. ').strip() for i in split_names]
        if last_name in ['jnr', 'jr', 'junior']:
            last_name = first_names.pop()
        for item in first_names:
            if item in ['ben', 'van', 'der', 'de', 'la', 'le']:
                last_name = first_names.pop() + ' ' + last_name
        authors.append(f'"{" ".join(first_names)} {last_name}"')
    return authors


def clean_bibtex_str(s):
    """Clean BibTeX string and escape TOML special characters"""
    s = s.replace('\\', '')
    s = s.replace('"', '\\"')
    s = s.replace('{', '').replace('}', '')
    s = s.replace('\t', ' ').replace('\n', ' ').replace('\r', '')
    return s


def clean_bibtex_tags(s, normalize=False):
    """Clean BibTeX keywords and convert to TOML tags"""
    tags = clean_bibtex_str(s).split(',')
    tags = [f'"{tag.strip()}"' for tag in tags]
    if normalize:
        tags = [tag.lower().capitalize() for tag in tags]
    tags_str = ', '.join(tags)
    return tags_str


def month2number(month):
    """Convert BibTeX month to numeric"""
    # print(month)
    month_abbr = month.strip()[:3].title()
    try:
        return str(list(calendar.month_abbr).index(month_abbr)).zfill(2)
    except ValueError:
        month_abbr = re.search(r'[0-9]{2}-[0-9]{2}\s([a-zA-Z]+)', month).group(1)
        return str(list(calendar.month_abbr).index(month_abbr)).zfill(2)

def check_duplicates(bib_dict):
    value_occurrences = collections.Counter(bib_dict.values())
    # print(value_occurrences)
    bib_duplicates = {key: value for key, value in bib_dict.items() if value_occurrences[value] > 1}
    duplicate_dict = defaultdict(list)
    for key,value in bib_duplicates.items():
        duplicate_dict[value].append(key)
    return duplicate_dict


def import_bibtex(bibtex, pub_dir='publication', featured=False, overwrite=False, normalize=False):
    """Import publications from BibTeX file"""

    # Check BibTeX file exists.
    if not Path(bibtex).is_file():
        print('Please check the path to your BibTeX file and re-run.')
        return

    # Load BibTeX file for parsing.
    with open(bibtex, 'r', encoding='utf-8') as bibtex_file:
        parser = BibTexParser(common_strings=True)
        parser.customization = convert_to_unicode
        bib_database = bibtexparser.load(bibtex_file, parser=parser)

        ## Remove duplicates with sample title
        bib_dict_full = bib_database.entries_dict
        bib_dict = dict(map(lambda kv : (kv[0], kv[1]['title']), bib_dict_full.items()))

        duplicate_dict = check_duplicates(bib_dict)
        print('Found %d duplicates.' % len(duplicate_dict))
        # pprint(dict(duplicate_dict.items()))
        print('Removing all preprints if proceedings/journals are available.')

        for title, bibkeys in duplicate_dict.items():
            for bibkey in bibkeys:
                if 'corr' in bibkey:
                    del bib_dict_full[bibkey]
                    del bib_dict[bibkey]

        duplicate_dict = check_duplicates(bib_dict)
        print('Found %d duplicates.' % len(duplicate_dict))
        pprint(dict(duplicate_dict.items()))
        print('Please, resolve these conflits by hand.')
        for key, entry in bib_dict_full.items():
            entry['ID'] = key
            parse_bibtex_entry(entry, pub_dir=pub_dir, featured=featured, overwrite=overwrite, normalize=normalize)


def parse_bibtex_entry(entry, pub_dir='publication', featured=False, overwrite=False, normalize=False):
    """Parse a bibtex entry and generate corresponding publication bundle"""
    verbose = False
    print(f"Parsing entry {entry['ID']}") if verbose else None

    bundle_path = f"content/{pub_dir}/{slugify(entry['ID'])}"
    markdown_path = os.path.join(bundle_path, 'index.md')
    # cite_path = os.path.join(bundle_path, f"{slugify(entry['ID'])}.bib")
    cite_path = os.path.join(bundle_path, 'cite.bib')
    date = datetime.utcnow()
    timestamp = date.isoformat('T') + 'Z'  # RFC 3339 timestamp.

    # Do not overwrite publication bundle if it already exists.
    if not overwrite and os.path.isdir(bundle_path):
        print(f'Skipping creation of {bundle_path} as it already exists. To overwrite, add the `--overwrite` argument.')
        return

    # Create bundle dir.
    print(f'Creating folder {bundle_path}') if verbose else None
    Path(bundle_path).mkdir(parents=True, exist_ok=True)

    # Save citation file.
    print(f'Saving citation to {cite_path}') if verbose else None
    db = BibDatabase()
    db.entries = [entry]
    writer = BibTexWriter()
    with open(cite_path, 'w', encoding='utf-8') as f:
        f.write(writer.write(db))

    # Prepare YAML front matter for Markdown file.
    frontmatter = ['---']
    frontmatter.append(f'title: "{clean_bibtex_str(entry["title"])}"')
    if 'month' in entry:
        frontmatter.append(f"date: {entry['year']}-{month2number(entry['month'])}-01")
    else:
        frontmatter.append(f"date: {entry['year']}-01-01")

    # frontmatter.append(f"publishDate: {timestamp}")

    authors = None
    if 'author' in entry:
        authors = entry['author']
    elif 'editor' in entry:
        authors = entry['editor']
    if authors:
        authors = clean_bibtex_authors([i.strip() for i in authors.replace('\n', ' ').split(' and ')])
        frontmatter.append(f"authors: [{', '.join(authors)}]")

    frontmatter.append(f'publication_types: ["{PUB_TYPES.get(entry["ENTRYTYPE"], 0)}"]')

    # if 'abstract' in entry:
    #     frontmatter.append(f'abstract: "{clean_bibtex_str(entry["abstract"])}"')
    # else:
    frontmatter.append('abstract: ""') 

    frontmatter.append(f'featured: {str(featured).lower()}')

    # Publication name.
    if 'booktitle' in entry:
        frontmatter.append(f'publication: "*{clean_bibtex_str(entry["booktitle"])}*"')
    elif 'journal' in entry:
        frontmatter.append(f'publication: "*{clean_bibtex_str(entry["journal"])}*"')
    else:
        frontmatter.append('publication: ""')

    if 'keywords' in entry:
        frontmatter.append(f'tags: [{clean_bibtex_tags(entry["keywords"], normalize)}]')

    if 'url' in entry:
        frontmatter.append(f'url_pdf: "{clean_bibtex_str(entry["url"])}"')

    if 'doi' in entry:
        frontmatter.append(f'doi: "{entry["doi"]}"')

    frontmatter.append('---\n\n')

    # Save Markdown file.
    try:
        print(f"Saving Markdown to '{markdown_path}'") if verbose else None
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(frontmatter))
    except IOError:
        print('ERROR: could not save file.')



if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f'Generate publications for academic website',
        formatter_class=RawTextHelpFormatter)
    parser.add_argument('--path', type=str, required=True, default='bib/')
    parser.add_argument("--overwrite", action='store_true', help='Overwrite existing publications')
    args = parser.parse_args()

    if os.path.isfile(args.path):
        import_bibtex(args.path, pub_dir='publication', featured=False, overwrite=args.overwrite, normalize=False)
    elif os.path.isdir(args.path):
        bibs = glob(args.path + '**/*.bib', recursive=True)
        # Merge all bib files in one
        with open('bib/summary.bib','wb') as wfd:
            for f in bibs:
                print(f)
                with open(f,'rb') as fd:
                    shutil.copyfileobj(fd, wfd)
        import_bibtex('bib/summary.bib', pub_dir='publication', featured=False, overwrite=args.overwrite, normalize=False)
        os.remove('bib/summary.bib')
    else:
        print('Error: Invalid path')
        quit(-1)

    