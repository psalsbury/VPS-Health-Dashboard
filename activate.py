"""Run as root on the server after health.salsbury.co.uk resolves to it."""
import pathlib, subprocess
subprocess.run(['certbot','certonly','--webroot','-w','/var/www/health.salsbury.co.uk/public_html','-d','health.salsbury.co.uk','--non-interactive','--agree-tos','--register-unsafely-without-email'],check=True)
config='''<VirtualHost *:80>
ServerName health.salsbury.co.uk
DocumentRoot /var/www/health.salsbury.co.uk/public_html
<Directory /var/www/health.salsbury.co.uk/public_html>
Options -Indexes
AllowOverride None
Require all granted
</Directory>
RewriteEngine On
RewriteCond %{REQUEST_URI} !^/\\.well-known/acme-challenge/
RewriteRule ^ https://health.salsbury.co.uk%{REQUEST_URI} [R=301,L]
</VirtualHost>
<VirtualHost *:443>
ServerName health.salsbury.co.uk
SSLEngine On
SSLCertificateFile /etc/letsencrypt/live/health.salsbury.co.uk/fullchain.pem
SSLCertificateKeyFile /etc/letsencrypt/live/health.salsbury.co.uk/privkey.pem
Include /etc/letsencrypt/options-ssl-apache.conf
ProxyRequests Off
ProxyPass / http://127.0.0.1:9187/
ProxyPassReverse / http://127.0.0.1:9187/
<Location />
AuthType Basic
AuthName "Salsbury server health"
AuthBasicProvider file
AuthUserFile /etc/apache2/salsbury-health.htpasswd
Require valid-user
</Location>
Header always set X-Robots-Tag "noindex, nofollow"
Header always set X-Content-Type-Options "nosniff"
Header always set X-Frame-Options "DENY"
Header always set Referrer-Policy "no-referrer"
Header always set Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
ErrorLog ${APACHE_LOG_DIR}/salsbury-health-error.log
CustomLog ${APACHE_LOG_DIR}/salsbury-health-access.log combined
</VirtualHost>
'''
path=pathlib.Path('/etc/apache2/sites-available/health.salsbury.co.uk.conf')
old=path.read_text(); path.write_text(config)
try:
    subprocess.run(['apache2ctl','configtest'],check=True)
    subprocess.run(['systemctl','reload','apache2'],check=True)
except Exception:
    path.write_text(old); raise
hook=pathlib.Path('/etc/letsencrypt/renewal-hooks/deploy/salsbury-health-reload')
hook.write_text('#!/bin/sh\n/usr/sbin/apache2ctl configtest && /bin/systemctl reload apache2\n')
hook.chmod(0o755)
print('HTTPS dashboard activated; password protection enabled.')
