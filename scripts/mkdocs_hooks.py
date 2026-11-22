"""Sitemap lastmod from each page's latest git commit, and landing-page head tags.

MkDocs writes <lastmod> when page.update_date is set. The default is the build
day (or SOURCE_DATE_EPOCH), which is not the file's commit date. This hook
replaces it with the committer time of the last commit that touched the source,
converted to America/Phoenix. Pages deploy needs a full git history
(actions/checkout fetch-depth: 0) for dates older than the tip commit.

The home page also gets og:description (the same text as meta description) and
JSON-LD dateModified from the generated date_modified front matter.
"""
import html as html_lib
import json, os, re, subprocess
from datetime import datetime, timezone, timedelta

_DATES = None

def _mst():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo('America/Phoenix')
    except Exception:
        return timezone(timedelta(hours=-7))

def _to_mst(iso):
    dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_mst())
    return dt.astimezone(_mst()).replace(microsecond=0).isoformat(timespec='seconds')

def _commit_dates():
    global _DATES
    if _DATES is not None:
        return _DATES
    dates = {}
    try:
        raw = subprocess.check_output(['git', 'log', '--format=%cI', '--name-only'], text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, OSError):
        _DATES = dates
        return dates
    current = None
    stamp = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})')
    for line in raw.splitlines():
        if stamp.fullmatch(line):
            current = _to_mst(line)
            continue
        if line and current and line not in dates:
            dates[line] = current
    _DATES = dates
    return dates

def on_pre_page(page, config, files):
    src = getattr(page.file, 'src_path', '') or ''
    rel = 'docs/' + src.replace('\\', '/')
    iso = _commit_dates().get(rel)
    if not iso:
        try:
            root = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True, stderr=subprocess.DEVNULL).strip()
            full = os.path.relpath(page.file.abs_src_path, root).replace('\\', '/')
            iso = _commit_dates().get(full)
        except (subprocess.CalledProcessError, OSError, ValueError):
            iso = None
    if iso:
        page.update_date = iso
    else:
        mtime = os.path.getmtime(page.file.abs_src_path)
        page.update_date = datetime.fromtimestamp(mtime, _mst()).date().isoformat()
    return page

def on_post_page(output, page, config):
    meta = page.meta or {}
    desc = meta.get('description') or config.get('site_description') or ''
    if desc and 'property="og:description"' not in output and '</head>' in output:
        output = output.replace('</head>', f'<meta property="og:description" content="{html_lib.escape(desc, quote=True)}"></head>', 1)
    if getattr(page.file, 'src_path', '') == 'index.md' and meta.get('date_modified') and '</head>' in output:
        payload = {
            '@context': 'https://schema.org',
            '@type': 'WebPage',
            'name': config.site_name,
            'url': page.canonical_url,
            'description': desc,
            'dateModified': meta['date_modified'],
        }
        tag = '<script type="application/ld+json">' + json.dumps(payload, ensure_ascii=False) + '</script>'
        output = output.replace('</head>', tag + '</head>', 1)
    return output
