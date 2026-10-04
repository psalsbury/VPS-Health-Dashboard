import json, os, pathlib, shutil, socket, ssl, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import deque

ROOT = pathlib.Path(__file__).parent
history = deque(maxlen=2880)
lock = threading.Lock()
latest = {}
SERVICES = {'apache2':'Web server','dovecot':'Incoming mail','postfix@-':'Outgoing mail','opendkim':'Mail signing','rspamd':'Spam filtering','redis-server':'Redis','cron':'Scheduled tasks','sentinelx-cloud-core':'Server connection'}
SITES = ['salsbury.co.uk','louisesalsbury.com','clubdailyfive.com','predictioncomp.com']
site_results = []
def run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=8)
    return p.stdout.strip()
def cpu():
    a = list(map(int,pathlib.Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    return sum(a), a[3]+a[4]
def websites():
    global site_results
    while True:
        results=[]
        for domain in SITES:
            t=time.monotonic()
            try:
                import urllib.request
                with urllib.request.urlopen('https://'+domain,timeout=8) as response:
                    status=response.status
                with socket.create_connection((domain,443),timeout=5) as raw:
                    with ssl.create_default_context().wrap_socket(raw,server_hostname=domain) as conn:
                        expires=ssl.cert_time_to_seconds(conn.getpeercert()['notAfter'])
                results.append(dict(name=domain,ok=200<=status<400,code=status,ms=round((time.monotonic()-t)*1000),certificate_days=int((expires-time.time())/86400)))
            except Exception:
                results.append(dict(name=domain,ok=False,error='Website or HTTPS certificate check failed'))
        site_results=results
        time.sleep(60)
def collect():
    global latest
    previous=cpu()
    while True:
        time.sleep(5)
        try:
            current=cpu(); delta=current[0]-previous[0]
            use=round(100*(1-(current[1]-previous[1])/delta),1) if delta else 0
            previous=current
            mem={k:int(v.split()[0]) for k,v in (line.split(':',1) for line in pathlib.Path('/proc/meminfo').read_text().splitlines())}
            disk=shutil.disk_usage('/')
            states=[dict(name=label,unit=unit,state=run(['systemctl','is-active',unit])) for unit,label in SERVICES.items()]
            failed=run(['systemctl','--failed','--no-legend','--plain']).splitlines()
            timers=json.loads(run(['systemctl','list-timers','--all','--output=json']))
            jobs=[]
            for item in timers:
                if any(word in item.get('unit','') for word in ['predictioncomp','clubdailyfive','player-wordle']):
                    service=item.get('activates')
                    if not service: continue
                    props=run(['systemctl','show',service,'-p','Result','-p','ExecMainStatus','-p','ActiveState'])
                    data=dict(line.split('=',1) for line in props.splitlines() if '=' in line)
                    jobs.append(dict(name=item['unit'].removesuffix('.timer'),last=item.get('last'),next=item.get('next'),result=data.get('Result','unknown'),state=data.get('ActiveState','unknown')))
            snapshot=dict(time=time.time(),hostname=socket.gethostname(),cpu=use,memory=round(100*(1-mem['MemAvailable']/mem['MemTotal']),1),memory_total=mem['MemTotal']/1048576,disk=round(100*disk.used/disk.total,1),disk_free=disk.free/1073741824,uptime=float(pathlib.Path('/proc/uptime').read_text().split()[0]),load=list(os.getloadavg()),cores=os.cpu_count(),services=states,failed=[x.split()[0] for x in failed if x.strip()],sites=site_results,jobs=jobs,reboot=pathlib.Path('/var/run/reboot-required').exists())
            alerts=[]
            for key,label in [('cpu','CPU'),('memory','Memory'),('disk','Disk')]:
                if snapshot[key]>=85: alerts.append(label+' usage is above 85%')
            for s in states:
                if s['state']!='active': alerts.append(s['name']+' is '+s['state'])
            for s in site_results:
                if not s['ok']: alerts.append(s['name']+' check failed')
                elif s['certificate_days']<14: alerts.append(s['name']+' HTTPS certificate expires within 14 days')
            if failed: alerts.append(str(len(failed))+' failed system services')
            for j in jobs:
                if j['result'] not in ['success','unknown']: alerts.append(j['name']+' last run: '+j['result'])
            snapshot['alerts']=alerts
            with lock:
                history.append({k:snapshot[k] for k in ['time','cpu','memory','disk']})
                latest=snapshot
        except Exception:
            import traceback; traceback.print_exc()
            with lock: latest={**latest,'collector_error':True}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/api/health':
            with lock: body=json.dumps(dict(latest,history=list(history))).encode()
            content='application/json'
        elif self.path in ['/','/index.html']:
            body=(ROOT/'index.html').read_bytes(); content='text/html; charset=utf-8'
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header('Content-Type',content); self.send_header('Cache-Control','no-store'); self.send_header('X-Robots-Tag','noindex, nofollow'); self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass
if __name__=='__main__':
    threading.Thread(target=websites,daemon=True).start()
    threading.Thread(target=collect,daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1',9187),Handler).serve_forever()
