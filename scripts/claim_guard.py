"""Claim guard (runs in CI after `mkdocs build`).
Fails if:
  1. any protected status line / claim boundary (claims/protected_lines.json) is missing from the built page;
  2. `scientific_breakthrough: true` (or any value other than false) appears anywhere in docs/;
  3. a claim id in the base branch's claims ledger disappears, or its status is upgraded
     (open/corrected/stopped/not claimed -> restricted -> supported);
  4. docs/claims.jsonl is not identical to claims/ledger.jsonl;
  5. the site-wide boundaries (banner, license) are gone;
  6. a run-log or progress entry datetime is later than the HEAD commit time or the current time.
     Comparison is timezone-aware. A date-only stamp is 00:00 America/Phoenix (MST, UTC-7, no daylight saving).
     A clock time in h:mm AM/PM is that clock time in America/Phoenix. An ISO datetime keeps its own offset.
usage: python scripts/claim_guard.py [BASE_LEDGER_FILE]

The ceiling is the earlier of the HEAD committer time and the current time. Set ATLAS_HEAD_SHA
to also consider that commit (CI passes the pull-request head so a synthetic merge commit cannot
move the ceiling later than the commit that carries the stamp).
"""
import sys,re,json,glob,os,subprocess
from datetime import datetime,timezone,timedelta
from bs4 import BeautifulSoup

def _mst():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo('America/Phoenix')
    except Exception:
        return timezone(timedelta(hours=-7))
MST=_mst()

def aware(dt):
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=MST)

def parse_stamp(s):
    """Aware datetime. Empty input is None. A YYYY-MM-DD date is 00:00 America/Phoenix."""
    if s is None: return None
    s=str(s).strip()
    if not s: return None
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',s):
        y,m,d=(int(x) for x in s.split('-'))
        return datetime(y,m,d,tzinfo=MST)
    return aware(datetime.fromisoformat(s.replace('Z','+00:00')))

def clock_of(date, time_mst=None, datetime_mst=None):
    """Full ISO datetime_mst wins. Else date plus h:mm AM/PM in America/Phoenix. Else the date at 00:00 MST."""
    raw=None if datetime_mst is None else str(datetime_mst).strip()
    if raw and raw!=str(date or ''):
        return parse_stamp(raw)
    if time_mst:
        m=re.match(r'(\d{1,2}):(\d{2}) (AM|PM)$',time_mst)
        if not m or not date: raise ValueError(f'unparsed time_mst {time_mst!r} date {date!r}')
        hh=int(m.group(1))%12+(12 if m.group(3)=='PM' else 0)
        return parse_stamp(date).replace(hour=hh,minute=int(m.group(2)),second=0,microsecond=0)
    return parse_stamp(date) if date else None

def head_commit_time():
    """Earliest committer time among ATLAS_HEAD_SHA (if set) and HEAD. None if git cannot answer."""
    specs=[]
    sha=os.environ.get('ATLAS_HEAD_SHA','').strip()
    if sha: specs.append(sha)
    specs.append('HEAD')
    times=[]
    for spec in specs:
        try:
            raw=subprocess.check_output(['git','log','-1','--format=%cI',spec],text=True,stderr=subprocess.DEVNULL).strip()
            if raw: times.append(aware(datetime.fromisoformat(raw)))
        except (subprocess.CalledProcessError,OSError,ValueError):
            continue
    return min(times) if times else None

def stamp_ceiling():
    """(ceiling, label). The stamp must not be later than the HEAD commit time or now."""
    now=datetime.now(timezone.utc)
    ht=head_commit_time()
    if ht is None: return now,'current time'
    if ht<=now: return ht,'HEAD commit time'
    return now,'current time'

def iter_records(path):
    if not os.path.exists(path): return
    if path.endswith('.jsonl'):
        for line in open(path,encoding='utf-8'):
            if line.strip(): yield json.loads(line)
        return
    data=json.load(open(path,encoding='utf-8'))
    if isinstance(data,dict):
        yield from data.get('events') or data.get('entries') or []
    elif isinstance(data,list):
        yield from data

def future_stamp_errors():
    """Run-log entries (source and generated feeds) and progress entries. Returns (errors, checked, ceiling, label)."""
    ceil,which=stamp_ceiling()
    errs=[]; n=0
    def consider(path, ident, dt):
        nonlocal n
        if dt is None: return
        n+=1
        if dt>ceil:
            errs.append(f'{path}: {ident} datetime {dt.isoformat()} is later than {which} {ceil.isoformat()}')
    for path in ('comms/bot_comms.jsonl','docs/bot_comms.jsonl','docs/bot_comms.json'):
        for c in iter_records(path):
            if not isinstance(c,dict) or c.get('channel_type')!='run-log': continue
            ident=c.get('id','?')
            try: dt=clock_of(c.get('date'),c.get('time_mst'),c.get('datetime_mst'))
            except ValueError as e:
                errs.append(f'{path}: {ident} has an unparseable datetime ({e})'); continue
            consider(path,ident,dt)
    for path in ('docs/progress.jsonl','docs/progress.json','progress/seed.jsonl'):
        for c in iter_records(path):
            if not isinstance(c,dict): continue
            ident=c.get('id','?')
            try: dt=clock_of(c.get('date'),c.get('time_mst'),c.get('datetime') or c.get('datetime_mst'))
            except ValueError as e:
                errs.append(f'{path}: {ident} has an unparseable datetime ({e})'); continue
            consider(path,ident,dt)
    return errs,n,ceil,which

def main():
    ERR=[]
    def key(t): return re.sub(r'[^\w]','',re.sub(r'\s+',' ',t.replace('·',' ')).lower())
    # 1 protected lines
    prot=json.load(open('claims/protected_lines.json'))
    for path,lines in prot.items():
        f='site/'+path
        if not os.path.exists(f): ERR.append(f'protected page removed: {path} ({len(lines)} protected lines)'); continue
        s=BeautifulSoup(open(f,encoding='utf-8').read(),'lxml'); a=s.select_one('article') or s
        k=key(a.get_text('\n'))
        for l in lines:
            if key(l) not in k: ERR.append(f'{path}: protected line missing or changed: "{l}"')
    # 2 scientific_breakthrough
    for f in glob.glob('docs/**/*',recursive=True)+['mkdocs.yml','overrides/main.html']:
        if os.path.isdir(f) or not f.endswith(('.md','.html','.txt','.json','.jsonl','.yml')): continue
        for m in re.finditer(r'scientific_breakthrough["\']?\s*[:=]\s*["\']?(\w+)',open(f,encoding='utf-8',errors='replace').read()):
            if m.group(1).lower()!='false': ERR.append(f'{f}: scientific_breakthrough set to {m.group(1)}')
    # 3/4 claims ledger
    RANK={'supported':2,'restricted':1}
    def load(p): return {c['id']:c for c in (json.loads(l) for l in open(p,encoding='utf-8') if l.strip())}
    head=load('claims/ledger.jsonl')
    base=load(sys.argv[1]) if len(sys.argv)>1 and os.path.exists(sys.argv[1]) else load('claims/ledger.jsonl')
    for i,c in base.items():
        if i not in head: ERR.append(f'claim removed from ledger: {i}'); continue
        b,h=c.get('status',''),head[i].get('status','')
        if RANK.get(h.lower(),0)>RANK.get(b.lower(),0): ERR.append(f'claim {i} status upgraded {b} -> {h}')
    if open('docs/claims.jsonl','rb').read()!=open('claims/ledger.jsonl','rb').read():
        ERR.append('docs/claims.jsonl differs from claims/ledger.jsonl (published ledger must equal the reviewed ledger)')
    # 5 site-wide
    banner=open('overrides/main.html').read()
    for p in ['scientific_breakthrough: false','Pillar 3 open','Not a completed Theory of Everything']:
        if p not in banner: ERR.append(f'site banner lost: "{p}"')
    if 'Source-available for noncommercial research and evaluation only' not in open('mkdocs.yml').read(): ERR.append('license line removed from mkdocs.yml')
    # 6 future run-log / progress stamps
    stamp_errs,nstamp,ceil,which=future_stamp_errors()
    ERR.extend(stamp_errs)
    if ERR:
        print('CLAIM GUARD FAILED:'); [print(' -',e) for e in ERR]; sys.exit(1)
    print(f'claim guard OK: {sum(map(len,prot.values()))} protected lines on {len(prot)} pages, {len(head)} ledger claims, none removed or upgraded; timestamp guard OK: {nstamp} run-log/progress stamps at or before {which} {ceil.isoformat()}')

if __name__=='__main__': main()
