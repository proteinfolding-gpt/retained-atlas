"""Build the bot communications feed: how the bots that maintain this wiki coordinate.
Run by build_machine_files.py (before build_ai_surfaces.py, which adds the events to search.json and llms-full.txt).

Input (hand-curated, one event per line): comms/bot_comms.jsonl; roster and credits: comms/bots.json.
Output:
  docs/bot_comms.jsonl  primary machine feed, one event per line, oldest first
  docs/bot_comms.json   same events + roster, credits, field definitions
  docs/bot_comms.txt    short newest-first text tail
  docs/wiki/bot-communications.md  the timeline table between the bot-comms markers

Rules: coordination log only, not research progress. Every event is "Not claimed"; events tied to the
WetLabEngine research branch or an unmerged PR are also labelled "not on main". Private messages are
summarized in plain words, never quoted. This script never touches claims or statuses."""
import json,os,re
BASE=os.environ.get('SITE_URL','https://proteinfolding-grokbot.github.io/retained-atlas/').rstrip('/')
SRC,ROSTER,PAGE='comms/bot_comms.jsonl','comms/bots.json','docs/wiki/bot-communications.md'
TYPES=['handoff','run-log','commit','heartbeat','pr-comment','pr-event']
LOCS={'wiki_main':'Not claimed','wiki_ops':'Not claimed','wiki_pr_open':'Not claimed · not on main','research_branch':'Not claimed · not on main'}

def minutes(t):
    m=re.match(r'(\d{1,2}):(\d{2}) (AM|PM)$',t or '')
    return (int(m.group(1))%12+(12 if m.group(3)=='PM' else 0))*60+int(m.group(2)) if m else None

# Source rows may carry datetime_mst with seconds (America/Phoenix). Rebuilding the
# clock from time_mst ("h:mm AM/PM") used to force ":00" and drop those seconds.
ISO_DT=re.compile(r'^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})([+-]\d{2}:\d{2}|Z)$')

def recorded_datetime(c, mn):
    raw=(c.get('datetime_mst') or '').strip()
    if raw:
        m=ISO_DT.match(raw)
        if not m: raise SystemExit(f"bot_comms {c['id']}: datetime_mst {raw!r} must be YYYY-MM-DDTHH:MM:SS±HH:MM")
        if m.group(1)!=c['date']: raise SystemExit(f"bot_comms {c['id']}: datetime_mst date {m.group(1)} != {c['date']}")
        if mn is not None and mn!=int(m.group(2))*60+int(m.group(3)):
            raise SystemExit(f"bot_comms {c['id']}: datetime_mst {raw} does not match time_mst {c.get('time_mst')}")
        return raw  # keep the recorded seconds
    if mn is not None: return c['date']+f'T{mn//60:02d}:{mn%60:02d}:00-07:00'
    return c['date']

def when_label(date, time_mst, datetime_mst, from_source):
    when=date[5:].replace('-','/')
    clock=time_mst or ''
    sec=ISO_DT.match(datetime_mst or '')
    if clock and sec and sec.group(4)!='00':
        clock=re.sub(r' (AM|PM)$', f':{sec.group(4)} \\1', clock)
    if clock: when+=' '+clock
    if from_source and datetime_mst: when+=' ('+datetime_mst+')'
    return when

def ref(u):
    repo='wiki' if '/retained-atlas/' in u else 'WetLabEngine'
    for pat,typ,fmt in ((r'issuecomment-(\d+)','pr-comment','comment {}'),(r'/actions/runs/(\d+)','review-run','run {}'),
                        (r'/commit/([0-9a-f]{7,40})','commit','{}'),(r'/pull/(\d+)$','pr',repo+' PR #{}')):
        m=re.search(pat,u)
        if m: return {'type':typ,'label':fmt.format(m.group(1)[:7] if typ=='commit' else m.group(1)),'repo':repo,'url':u}
    return {'type':'link','label':'link','repo':repo,'url':u}

def build():
    if not os.path.exists(SRC): return
    ev=[]
    for l in open(SRC,encoding='utf-8'):
        if not l.strip(): continue
        c=json.loads(l)
        if c['channel_type'] not in TYPES: raise SystemExit(f"bot_comms {c['id']}: channel_type must be one of {TYPES}")
        if c['location'] not in LOCS: raise SystemExit(f"bot_comms {c['id']}: unknown location {c['location']}")
        mn=minutes(c.get('time_mst'))
        raw_dt=(c.get('datetime_mst') or '').strip()
        dt=recorded_datetime(c, mn)
        ev.append({'id':c['id'],'date':c['date'],'time_mst':c.get('time_mst'),
          'datetime_mst':dt,'when':when_label(c['date'],c.get('time_mst'),dt,bool(raw_dt)),
          'from':c['from'],'to':c['to'],'channel_type':c['channel_type'],'summary':c['summary'],
          'refs':[ref(u) for u in c.get('refs') or []],'status_label':LOCS[c['location']],'location':c['location'],
          'source':c['source'],'does_not_show':c.get('does_not_show')})
    ev.sort(key=lambda e:(e['date'],minutes(e['time_mst']) if e['time_mst'] else 24*60,e['id']))
    whens={e['id']:e.pop('when') for e in ev}
    roster=json.load(open(ROSTER,encoding='utf-8')) if os.path.exists(ROSTER) else {}
    with open('docs/bot_comms.jsonl','w',encoding='utf-8') as o:
        for e in ev: o.write(json.dumps(e,ensure_ascii=False)+'\n')
    json.dump({'schema':'retained-atlas.bot-comms/v2','base':BASE,'page':BASE+'/wiki/bot-communications/','time_zone':'America/Phoenix (MST, UTC-7, no daylight saving)',
      **roster,
      'fields':{'id':'stable event id','date':'YYYY-MM-DD in MST','time_mst':'h:mm AM/PM in MST, or null if not recorded',
        'datetime_mst':'ISO 8601 with -07:00 offset, including seconds when the source recorded them (date only when the time was not recorded)','from':'who acted','to':'who it was for',
        'channel_type':' | '.join(TYPES),'summary':'plain-language summary; private messages are summarized, never quoted',
        'refs':'list of {type: commit|pr|pr-comment|review-run|link, label, repo: wiki|WetLabEngine, url}',
        'status_label':'"Not claimed" or "Not claimed · not on main"','location':' | '.join(LOCS),
        'source':'where the event was read from','does_not_show':'boundary, when stated'},
      'rules':['Coordination log only: not research progress, never a claim, never changes a status.',
               'Anything labelled "not on main" is on the WetLabEngine research branch or in an unmerged pull request.',
               'For research results use /progress.jsonl and the page badges, not this feed.','scientific_breakthrough: false'],
      'counts':{t:sum(e['channel_type']==t for e in ev) for t in TYPES},'count':len(ev),'events':ev},
      open('docs/bot_comms.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
    T=['# Retained Atlas — bot communications (newest first)','',f'Feed: {BASE}/bot_comms.jsonl · {BASE}/bot_comms.json · page: {BASE}/wiki/bot-communications/',
       'Coordination log, not research progress. Every event is Not claimed. Times are MST. scientific_breakthrough: false','']
    for e in reversed(ev[-40:]):
        T.append(f"{e['datetime_mst']} [{e['channel_type']}] [{e['status_label']}] {e['from']} -> {e['to']}: {e['summary']}")
    open('docs/bot_comms.txt','w',encoding='utf-8').write('\n'.join(T)+'\n')
    if not os.path.exists(PAGE): return
    cell=lambda t:(t or '').replace('|','\\|').replace('\n',' ')
    rows=['| When (MST) | From → to | Type | What happened | Links |','| --- | --- | --- | --- | --- |']
    for e in ev:
        if e['channel_type']=='commit' and e['to']=='wiki PR #6' and e['id'].startswith('wiki-pr6-'): continue
        when=whens.get(e['id']) or e['date'][5:].replace('-','/')+(' '+e['time_mst'] if e['time_mst'] else '')
        links=', '.join(f"[{r['label']}]({r['url']})" for r in e['refs']) or 'private, summarized'
        nm=' · not on main' if 'not on main' in e['status_label'] else ''
        rows.append('| '+' | '.join(cell(x) for x in [when,f"{e['from']} → {e['to']}",e['channel_type']+nm,e['summary'],links])+' |')
    pc=[e for e in ev if e['id'].startswith('wiki-pr6-')]
    who=lambda k:sum(e['from'].startswith(k) for e in pc)
    rows+=['',f"Wiki PR #6 also has {len(pc)} individual commits in the feed (type `commit`): {who('Retained Atlas Wiki Bot')} by Wiki Bot, "
           f"{who('Grok Bot')} by Grok Bot's nightly update, and {len(pc)-who('Retained Atlas Wiki Bot')-who('Grok Bot')} where no bot note recorded who pushed it."]
    pg=open(PAGE,encoding='utf-8').read()
    pg=re.sub(r'(<!-- bot-comms:timeline:start -->\n).*?(<!-- bot-comms:timeline:end -->)',lambda m:m.group(1)+'\n'+'\n'.join(rows)+'\n\n'+m.group(2),pg,flags=re.S)
    open(PAGE,'w',encoding='utf-8').write(pg)

if __name__=='__main__': build(); print('bot comms feed built')
