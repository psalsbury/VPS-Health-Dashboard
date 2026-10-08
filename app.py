import json, os, pathlib, re, shutil, socket, ssl, subprocess, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import deque

ROOT = pathlib.Path(__file__).parent
STATE = pathlib.Path(os.environ.get('STATE_DIRECTORY', '/var/lib/salsbury-server-health'))
PORT = int(os.environ.get('PORT', 9187))
history = deque(maxlen=2880)
lock = threading.Lock()
latest = {}
SERVICES = {'apache2':'Web server','dovecot':'Incoming mail','postfix@-':'Outgoing mail','opendkim':'Mail signing','rspamd':'Spam filtering','redis-server':'Redis','cron':'Scheduled tasks','sentinelx-cloud-core':'Server connection'}
SITES = ['salsbury.co.uk','louisesalsbury.com','clubdailyfive.com','predictioncomp.com']
# Certificates not covered by the website checks: (label, host, port)
CERTS = [('Mail server (IMAP)','mail.clubdailyfive.com',993),('This dashboard','health.salsbury.co.uk',443)]
CERT_WARN_DAYS = 21  # certbot renews at 30 days, so below 21 means renewal is failing
QUEUE_WARN = 20
site_results = []
cert_results = []
def run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=8)
    return p.stdout.strip()
def cpu():
    a = list(map(int,pathlib.Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    return sum(a), a[3]+a[4]
def cert_days(host,port):
    with socket.create_connection((host,port),timeout=5) as raw:
        with ssl.create_default_context().wrap_socket(raw,server_hostname=host) as conn:
            return int((ssl.cert_time_to_seconds(conn.getpeercert()['notAfter'])-time.time())/86400)
def reason(e):
    if isinstance(e,urllib.error.HTTPError): return 'Website returned HTTP '+str(e.code)
    e=getattr(e,'reason',e)
    if isinstance(e,ssl.SSLCertVerificationError): return 'HTTPS certificate is invalid ('+str(e.verify_message)+')'
    if isinstance(e,(socket.timeout,TimeoutError)): return 'Timed out'
    return 'Check failed ('+(str(e) or type(e).__name__)[:120]+')'
def websites():
    global site_results, cert_results
    while True:
        results=[]
        for domain in SITES:
            t=time.monotonic()
            try:
                with urllib.request.urlopen(urllib.request.Request('https://'+domain,headers={'User-Agent':'SalsburyHealth/1.0'}),timeout=8) as response:
                    status=response.status
                results.append(dict(name=domain,ok=200<=status<400,code=status,ms=round((time.monotonic()-t)*1000),certificate_days=cert_days(domain,443)))
            except Exception as e:
                results.append(dict(name=domain,ok=False,error=reason(e)))
        certs=[]
        for label,host,port in CERTS:
            try: certs.append(dict(name=label,host=host,ok=True,certificate_days=cert_days(host,port)))
            except Exception as e: certs.append(dict(name=label,host=host,ok=False,error=reason(e)))
        site_results=results; cert_results=certs
        time.sleep(60)
def updates():
    try: text=pathlib.Path('/var/lib/update-notifier/updates-available').read_text()
    except OSError: return None
    total=re.search(r'(\d+) updates? can be applied',text)
    security=re.search(r'(\d+) of these updates? (?:is a|are) standard security',text)
    return dict(total=int(total.group(1)) if total else 0,security=int(security.group(1)) if security else 0)
def reboot_info():
    flag=pathlib.Path('/var/run/reboot-required')
    if not flag.exists(): return None
    try: pkgs=sorted(set(pathlib.Path('/var/run/reboot-required.pkgs').read_text().split()))
    except OSError: pkgs=[]
    kernels=sorted((p.removeprefix('linux-image-') for p in pkgs if p.startswith('linux-image')),key=lambda v:[int(x) if x.isdigit() else 0 for x in re.split(r'[.-]',v)])
    return dict(since=flag.stat().st_mtime,packages=[p for p in pkgs if not p.startswith('linux-')]+(['Linux kernel '+kernels[-1]] if kernels else []))
def mail_queue():
    try: p=subprocess.run(['postqueue','-j'],capture_output=True,text=True,timeout=8)
    except Exception: return None
    return sum(1 for line in p.stdout.splitlines() if line.strip()) if p.returncode==0 else None
def save_history():
    with lock: data=list(history)
    try:
        tmp=STATE/'history.tmp'; tmp.write_text(json.dumps(data)); tmp.replace(STATE/'history.json')
    except OSError: pass
def load_history():
    try:
        cutoff=time.time()-5*history.maxlen
        history.extend(p for p in json.loads((STATE/'history.json').read_text()) if p['time']>cutoff)
    except (OSError,ValueError,KeyError,TypeError): pass
def collect():
    global latest
    previous=cpu()
    ticks=0
    while True:
        time.sleep(5)
        try:
            current=cpu(); delta=current[0]-previous[0]
            use=round(100*(1-(current[1]-previous[1])/delta),1) if delta else 0
            previous=current
            mem={k:int(v.split()[0]) for k,v in (line.split(':',1) for line in pathlib.Path('/proc/meminfo').read_text().splitlines())}
            disk=shutil.disk_usage('/')
            states=[dict(name=label,unit=unit,state=run(['systemctl','is-active',unit])) for unit,label in SERVICES.items()]
            failed=[x.split()[0] for x in run(['systemctl','--failed','--no-legend','--plain']).splitlines() if x.strip()]
            timers=json.loads(run(['systemctl','list-timers','--all','--output=json']))
            jobs=[]
            for item in timers:
                if any(word in item.get('unit','') for word in ['predictioncomp','clubdailyfive','player-wordle']):
                    service=item.get('activates')
                    if not service: continue
                    props=run(['systemctl','show',service,'-p','Result','-p','ExecMainStatus','-p','ActiveState'])
                    data=dict(line.split('=',1) for line in props.splitlines() if '=' in line)
                    jobs.append(dict(name=item['unit'].removesuffix('.timer'),last=item.get('last'),next=item.get('next'),result=data.get('Result','unknown'),state=data.get('ActiveState','unknown')))
            reboot=reboot_info(); queue=mail_queue()
            snapshot=dict(time=time.time(),hostname=socket.gethostname(),cpu=use,memory=round(100*(1-mem['MemAvailable']/mem['MemTotal']),1),memory_total=mem['MemTotal']/1048576,disk=round(100*disk.used/disk.total,1),disk_free=disk.free/1073741824,uptime=float(pathlib.Path('/proc/uptime').read_text().split()[0]),load=list(os.getloadavg()),cores=os.cpu_count(),services=states,failed=failed,sites=site_results,certs=cert_results,jobs=jobs,reboot=reboot,updates=updates(),mail_queue=queue)
            alerts=[]
            for key,label in [('cpu','CPU'),('memory','Memory'),('disk','Disk')]:
                if snapshot[key]>=85: alerts.append(label+' usage is above 85%')
            for s in states:
                if s['state']!='active': alerts.append(s['name']+' is '+s['state'])
            for s in site_results+cert_results:
                if not s['ok']: alerts.append(s['name']+': '+s['error'])
                elif s['certificate_days']<CERT_WARN_DAYS: alerts.append(s['name']+' HTTPS certificate expires in '+str(s['certificate_days'])+' days and has not renewed')
            if failed: alerts.append('Failed system services: '+', '.join(failed))
            for j in jobs:
                if j['result'] not in ['success','unknown']: alerts.append(j['name']+' last run: '+j['result'])
            if queue is not None and queue>=QUEUE_WARN: alerts.append(str(queue)+' emails are waiting in the outgoing mail queue')
            if reboot and time.time()-reboot['since']>14*86400: alerts.append('Server restart has been pending for '+str(int((time.time()-reboot['since'])/86400))+' days to finish installing updates')
            snapshot['alerts']=alerts
            with lock:
                history.append({k:snapshot[k] for k in ['time','cpu','memory','disk']})
                latest=snapshot
            ticks+=1
            if ticks%12==0: save_history()
        except Exception:
            import traceback; traceback.print_exc()
            with lock: latest={**latest,'collector_error':True}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/api/portfolio':
            try: body=(STATE/'portfolio.json').read_bytes()
            except OSError: body=b'{"error":"Statistics collector has not completed"}'
            content='application/json'
        elif self.path=='/api/health':
            with lock: body=json.dumps(dict(latest,history=list(history))).encode()
            content='application/json'
        elif self.path in ['/','/index.html']:
            body=(ROOT/'index.html').read_bytes(); content='text/html; charset=utf-8'
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header('Content-Type',content); self.send_header('Cache-Control','no-store'); self.send_header('X-Robots-Tag','noindex, nofollow'); self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass
if __name__=='__main__':
    load_history()
    threading.Thread(target=websites,daemon=True).start()
    threading.Thread(target=collect,daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
