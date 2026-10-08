"""Aggregate traffic estimates; no addresses or browser identifiers persisted."""
import collections,datetime as dt,gzip,pathlib,re,socket
from zoneinfo import ZoneInfo
UK=ZoneInfo('Europe/London')
PAT=re.compile(r'^([^ ]+) .*?\[([^]]+)\] "(\w+) ([^ ]+) [^"]+" (\d{3}) [^ ]+ "[^"]*" "([^"]*)"')
AUTO=re.compile(r'bot|spider|crawl|python|curl|wget|monitor|headless|uptime|facebookexternalhit|google-read-aloud|google-lens|l9scan|leakix|scanner|scan/|httpclient|go-http|okhttp|scrapy|selenium|playwright|puppeteer|axios|node-fetch|preview',re.I)
BROWSER=re.compile(r'Mozilla/5\.0.*(?:Chrome/|Firefox/|Safari/|Edg/)',re.I)
KEYS=('human_visits','human_home','crawlers','health_checks','uncertain','total_home')
def classify(ua,ip,local):
 if ua.startswith('SalsburyHealth/'):return 'health_checks'
 if ua.startswith('Python-urllib/') and ip in local:return 'health_checks'
 if AUTO.search(ua):return 'crawlers'
 return 'candidate' if BROWSER.search(ua) else 'uncertain'
def collect(domain,log,previous):
 local={'127.0.0.1','::1'}
 try:local.update(x[4][0] for x in socket.getaddrinfo(domain,443))
 except OSError:pass
 cutoff=(dt.datetime.now(UK).date()-dt.timedelta(days=366)).isoformat()
 rows={};sessions=collections.defaultdict(list);earliest=None
 for f in pathlib.Path('/var/log/apache2').glob(log+'*'):
  with (gzip.open if f.suffix=='.gz' else open)(f,'rt',errors='replace') as stream:
   for line in stream:
    m=PAT.search(line)
    if not m:continue
    ip,stamp,method,path,status,ua=m.groups()
    try:date=dt.datetime.strptime(stamp,'%d/%b/%Y:%H:%M:%S %z');day=date.astimezone(UK).date().isoformat()
    except ValueError:continue
    if day<cutoff:continue
    earliest=min(earliest or day,day)
    row=rows.setdefault(day,dict.fromkeys(KEYS,0))
    if method!='GET' or not 200<=int(status)<300:continue
    path=path.split('?',1)[0];home=path in ('/','/index.html','/index.php')
    kind=classify(ua,ip,local)
    if home:
     row['total_home']+=1
     if kind!='candidate':row[kind]+=1
    if kind=='candidate':
     # IP+UA used only in memory to estimate 30-minute sessions, never exported.
     evidence=path.startswith('/api/') or path.endswith(('.js','.css','.woff','.woff2'))
     sessions[(day,ip,ua)].append((date.timestamp(),home,evidence))
 for (day,ip,ua),records in sessions.items():
  records.sort();group=[];last=None
  def finish(group):
   n=sum(r[1] for r in group)
   if not n:return
   evidence=any(r[2] for r in group)
   if evidence and len(group)<300:
    rows[day]['human_visits']+=1;rows[day]['human_home']+=n
   else:rows[day]['uncertain']+=n
  for record in records:
   if last is not None and record[0]-last>1800:finish(group);group=[]
   group.append(record);last=record[0]
  finish(group)
 # Keep prior complete daily aggregates after raw logs expire. Do not keep obsolete classifications for reparsed days.
 for day,row in previous.get('days',{}).items():
  if day>=cutoff and (earliest is None or day<earliest):rows[day]=row
 for row in rows.values():assert row['total_home']==sum(row[k] for k in ('human_home','crawlers','health_checks','uncertain'))
 return {'days':rows,'available_from':min(x for x in [earliest,previous.get('available_from')] if x) if earliest or previous.get('available_from') else None,'definition':'Estimated visits: browser sessions with homepage and JS/CSS/font/API activity, 30-minute inactivity timeout, split at UK midnight. Automation can mimic this; estimates are not verified people. Other figures are successful homepage GET loads. No visitor identifiers retained.'}
