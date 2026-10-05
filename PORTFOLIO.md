# Website portfolio metrics
The password-protected dashboard combines four sites and server health.
Install portfolio.py alongside app.py. Install the supplied root oneshot service and minute timer with systemctl daemon-reload and enable --now salsbury-portfolio.timer. The HTTP application remains www-data and reads only aggregate JSON; databases are opened read-only by the collector.
Add CustomLog entries to each salsbury.co.uk and louisesalsbury.com virtual host, targeting /var/log/apache2/DOMAIN-metrics.log with combined format. Existing logs remain in place. Run apache2ctl configtest before reloading.
Homepage hits are successful GET requests to /, /index.html and /index.php, excluding recognised bots and monitors; they are not unique people. UK calendar-day totals (with each day's top 25 pages) are retained for 366 days, so the dashboard can show any week or month in the last year. Initial history is limited by available logs. No IPs, emails, credentials or user identifiers are exported.
Database metrics are cumulative; activity and traffic use the selected date range. Pharmacy and diabetes outcomes are not centrally tracked and are explicitly labelled unavailable.
