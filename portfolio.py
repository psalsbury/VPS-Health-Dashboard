#!/usr/bin/env python3
"""Read-only aggregate dashboard collector. Never exports identities or auth data."""
import datetime as dt, gzip, json, pathlib, re, sqlite3, time
from zoneinfo import ZoneInfo
ROOT=pathlib.Path('/opt/salsbury-server-health')
STATE=pathlib.Path('/var/lib/salsbury-server-health')
UK=ZoneInfo('Europe/London')
DOMAINS=['clubdailyfive.com','predictioncomp.com','louisesalsbury.com','salsbury.co.uk']
LOGS={'clubdailyfive.com':'clubdailyfive.com-access.log','predictioncomp.com':'predictioncomp.com-access.log','louisesalsbury.com':'louisesalsbury.com-metrics.log','salsbury.co.uk':'salsbury.co.uk-metrics.log'}
PAT=re.compile(r'\[([^]]+)\] "(\w+) ([^ ]+) [^"]+" (\d{3}) [^ ]+ "[^"]*" "([^"]*)"')
BOT=re.compile(r'bot|spider|crawler|python|curl|wget|monitor|headless|uptime',re.I)
def query(path,sql,args=()):
 with sqlite3.connect('file:'+path+'?mode=ro',uri=True,timeout=2) as c:
  c.execute('pragma query_only=on')
  return c.execute(sql,args).fetchall()
def scalar(path,sql,args=()):return query(path,sql,args)[0][0]
def traffic(domain):
 days={}; earliest=None; files=list(pathlib.Path('/var/log/apache2').glob(LOGS[domain]+'*'))
 cutoff=(dt.datetime.now(UK).date()-dt.timedelta(days=29)).isoformat()
 for p in files:
  if not p.is_file():continue
  opener=gzip.open if p.suffix=='.gz' else open
  with opener(p,'rt',errors='replace') as f:
   for line in f:
    match=PAT.search(line)
    if not match:continue
    stamp,method,path,status,ua=match.groups()
    if method!='GET':continue
    try:day=dt.datetime.strptime(stamp,'%d/%b/%Y:%H:%M:%S %z').astimezone(UK).date().isoformat()
    except ValueError:continue
    earliest=min(earliest or day,day)
    if day<cutoff:continue
    row=days.setdefault(day,dict(home=0,bots=0,requests=0,errors=0,pages={}))
    row['requests']+=1;row['errors']+=int(int(status)>=500)
    path=path.split('?',1)[0]
    if not 200<=int(status)<300:continue
    bot=bool(BOT.search(ua))
    if path in ['/','/index.html','/index.php']:
     row['bots' if bot else 'home']+=1
    if not bot and (path=='/' or path.endswith(('.html','.php'))):
     row['pages'][path]=row['pages'].get(path,0)+1
 return {'days':days,'available_from':earliest,'definition':'Successful GET requests to /, /index.html or /index.php; known bots and monitors excluded. Hits are not unique visitors.'}
def collect():
 data={'updated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'sites':{},'errors':[]}
 for domain in DOMAINS:
  site={'traffic':None,'metrics':{},'details':[]}
  try:site['traffic']=traffic(domain)
  except Exception as e:site['error']='Traffic unavailable: '+type(e).__name__
  data['sites'][domain]=site
 def block(domain,fn):
  try:fn(data['sites'][domain])
  except Exception as e:data['sites'][domain]['data_error']='Admin data unavailable: '+type(e).__name__
 def club(s):
  q='/var/lib/clubdailyfive/clubquiz.sqlite';w='/var/lib/clubdailyfive/player-wordle/game.sqlite3';a='/var/lib/clubdailyfive/analytics.sqlite'
  s['metrics']={'Active clubs':scalar(q,'select count(*) from clubs where active=1'),'Reviewed questions':scalar(q,"select count(*) from questions where status='reviewed'"),'Wordle players':scalar(w,'select count(*) from players'),'Open question reports':scalar(a,"select count(*) from question_reports where status='open'")}
  players=dict(query(w,'select c.slug,count(p.id) from clubs c left join players p on p.club_id=c.id group by c.id'))
  s['clubs']=[{'name':n,'slug':sl,'questions':num,'players':players.get(sl,0)} for sl,n,num in query(q,"select c.slug,c.name,sum(case when q.status='reviewed' then 1 else 0 end) from clubs c left join questions q on q.club_id=c.id where c.active=1 group by c.id order by c.name")]
  s['activity']= [{'date':d,'game':g,'event':e,'total':t} for d,g,e,t in query(a,'select event_date,game,event,sum(total) from game_funnel group by event_date,game,event')]
  s['runs']=[{'date':date,'status':status} for date,status in query(q,'select started_at,status from generation_runs order by id desc limit 5')]
  s['runs'] += [{'date':date,'status':status} for date,status in query(w,'select ran_at,status from agent_runs order by id desc limit 5')]
 def predictions(s):
  p='/var/lib/predictioncomp/predictioncomp.sqlite'
  s['metrics']={'Human accounts':scalar(p,'select count(*) from users where is_bot=0'),'Bots':scalar(p,'select count(*) from users where is_bot=1'),'Fixtures':scalar(p,'select count(*) from fixtures'),'Friend leagues':scalar(p,'select count(*) from leagues'),'Human predictions':scalar(p,'select count(*) from predictions p join users u on u.id=p.user_id where u.is_bot=0'),'Scored fixtures':scalar(p,'select count(*) from fixtures where home_score is not null and away_score is not null')}
  upcoming=query(p,"select round,count(*) from fixtures where kickoff_utc>strftime('%Y-%m-%dT%H:%M:%S','now') group by round order by min(kickoff_utc) limit 1")
  if upcoming:
   rnd,count=upcoming[0]
   s['next_round']={'round':rnd,'fixtures':count,'humans':scalar(p,'select count(distinct p.user_id) from predictions p join users u on u.id=p.user_id join fixtures f on f.id=p.fixture_id where f.round=? and u.is_bot=0',(rnd,)),'bots':scalar(p,'select count(distinct p.user_id) from predictions p join users u on u.id=p.user_id join fixtures f on f.id=p.fixture_id where f.round=? and u.is_bot=1',(rnd,))}
  s['activity']=[{'date':d,'game':'predictions','event':'saved','total':n} for d,n in query(p,"select date(saved_at),count(*) from predictions p join users u on u.id=p.user_id where u.is_bot=0 group by date(saved_at)")]
  s['details']=[{'label':k.replace('_',' ').title(),'value':d} for k,d in query(p,"select key,updated_at from sync_meta where key in ('last_daily_job','results_checked','published_refresh_success')")]
 def pharmacy(s):
  p='/var/lib/louisesalsbury/pharmacy_quiz.sqlite'
  s['metrics']={'Active drugs':scalar(p,'select count(*) from drugs where active=1'),'Quiz interactions':scalar(p,"select count(*) from interactions where quiz_enabled=1 and review_status='reviewed'"),'Pending reviews':scalar(p,"select count(*) from interactions where review_status='pending'")}
  s['details']=[{'label':'Latest evidence review','value':scalar(p,'select max(reviewed_on) from interactions')}]
  s['note']='Quiz completions are not currently recorded by this site; traffic is available below.'
 def diabetes(s):
  root=pathlib.Path('/var/www/salsbury.co.uk/public_html')
  s['metrics']={'Learning activities':len([p for p in root.glob('*.html') if 'quiz' in p.name or p.name in ['day-with-sam.html','symptom-sorter.html']])}
  s['note']='Learning outcomes and completions are stored on visitors’ devices, not centrally. Page hits show activity opens, not completions.'
 for domain,fn in [('clubdailyfive.com',club),('predictioncomp.com',predictions),('louisesalsbury.com',pharmacy),('salsbury.co.uk',diabetes)]:block(domain,fn)
 # Preserve complete daily aggregates as Apache rotates and removes old logs.
 try: old=json.loads((STATE/'portfolio.json').read_text())
 except (OSError,ValueError): old={}
 cutoff=(dt.datetime.now(UK).date()-dt.timedelta(days=29)).isoformat()
 for domain,site in data['sites'].items():
  prior=old.get('sites',{}).get(domain,{}).get('traffic') or {}
  fresh=site.get('traffic')
  if not fresh:
   if prior:
    site['traffic']=prior
    site['error']='Traffic collection failed; showing last available traffic snapshot.'
   continue
  starts=[x for x in [prior.get('available_from'),fresh.get('available_from')] if x]
  if starts:fresh['available_from']=min(starts)
  for day,row in prior.get('days',{}).items():
   if day<cutoff:continue
   current=fresh['days'].setdefault(day,dict(home=0,bots=0,requests=0,errors=0,pages={}))
   for key in ['home','bots','requests','errors']:current[key]=max(current.get(key,0),row.get(key,0))
   for page,n in row.get('pages',{}).items():current['pages'][page]=max(current['pages'].get(page,0),n)
 STATE.mkdir(exist_ok=True)
 tmp=STATE/'portfolio.tmp';tmp.write_text(json.dumps(data));tmp.chmod(0o640)
 import grp,os
 os.chown(tmp,0,grp.getgrnam('www-data').gr_gid)
 tmp.replace(STATE/'portfolio.json')
 return data
if __name__=='__main__':collect()
