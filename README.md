# VPS Health Dashboard

Live at https://health.salsbury.co.uk. A private Linux monitoring dashboard behind Apache HTTPS and Basic authentication.

## Included
- CPU, memory, root disk space, uptime and load.
- Key web and mail services, failed system services and restart-required status.
- Website availability and certificate expiry for the four configured websites.
- Last result and next run of website systemd timers.
- Resource history held in memory (up to 2,880 samples; resets on service restart).
- Automatic page refresh every 15 seconds; resource collection approximately every 5 seconds; website checks every minute.
- Stale readings and monitoring failures are shown as warnings.

## Files
- `app.py`: Python standard-library monitor and HTTP server.
- `index.html`: responsive dashboard.
- `deploy/salsbury-server-health.service`: restricted systemd service.
- `deploy/bootstrap-http.conf`: initial Apache virtual host for ACME validation.
- `activate.py`: certificate issuance, authenticated HTTPS proxy and renewal reload hook.

## Installation on Ubuntu with Apache
Requires Python 3.9+, systemd with JSON timer output, Apache 2, apache2-utils and Certbot. The installation paths and domains are specific to this server; review them before using elsewhere.

1. Put app.py, index.html and activate.py in `/opt/salsbury-server-health`, readable by www-data.
2. Create `/var/www/health.salsbury.co.uk/public_html`.
3. Install deploy/bootstrap-http.conf as `/etc/apache2/sites-available/health.salsbury.co.uk.conf`.
4. Enable the proxy, proxy_http, headers and rewrite modules and the health.salsbury.co.uk site.
5. Create authentication interactively with `sudo htpasswd -c /etc/apache2/salsbury-health.htpasswd pete`. Set root:www-data ownership and mode 640.
6. Install the supplied systemd service in /etc/systemd/system, run daemon-reload and enable --now salsbury-server-health.
7. Validate Apache configuration before reloading.
8. Point the health DNS A record to this server; ensure any AAAA record routes to the same server.
9. Run `sudo python3 /opt/salsbury-server-health/activate.py` to issue the certificate and activate HTTPS.

The activation script expects the initial Apache configuration to exist. It uses Certbot without a registration email; certificate expiry is monitored on the dashboard for the configured websites.

## Operations
```sh
sudo systemctl status salsbury-server-health
sudo journalctl -u salsbury-server-health -n 50 --no-pager
sudo systemctl restart salsbury-server-health
sudo htpasswd /etc/apache2/salsbury-health.htpasswd pete
```

The backend listens only on 127.0.0.1:9187. Authentication is enforced by Apache on both the page and API. Do not expose that backend directly. Collection is read-only; this dashboard does not restart services or repair failed jobs.

Passwords, htpasswd files, private keys and runtime readings are intentionally excluded from source control. This repository is public.

## Validation
The live deployment passed API collection, HTTPS certificate verification, authenticated page/API access, unauthenticated 401 checks and HTTP-to-HTTPS redirect checks.
