#!/usr/bin/env python3
"""Push a text message to whichever channels are configured via env vars.

Channels (all optional; set the secrets for the ones you use):
  ntfy      NTFY_TOPIC [NTFY_SERVER=https://ntfy.sh] [NTFY_TOKEN]
  Telegram  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  Discord   DISCORD_WEBHOOK_URL
  Email     EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVERS (comma-separated)
            [SMTP_SERVER=smtp.gmail.com] [SMTP_PORT=465]
"""
import json
import os
import smtplib
import sys
import urllib.request
from email.mime.text import MIMEText


def _post(url, data, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method='POST')
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status >= 300:
            raise RuntimeError(f'HTTP {resp.status}')


def _chunks(text, size):
    while text:
        cut = text.rfind('\n', 0, size) if len(text) > size else len(text)
        cut = cut if cut > 0 else size
        yield text[:cut]
        text = text[cut:].lstrip('\n')


def send_ntfy(title, body):
    topic = os.environ.get('NTFY_TOPIC')
    if not topic:
        return False
    server = os.environ.get('NTFY_SERVER', 'https://ntfy.sh').rstrip('/')
    headers = {'Title': title.encode('utf-8'), 'Tags': 'chart_with_upwards_trend'}
    if os.environ.get('NTFY_TOKEN'):
        headers['Authorization'] = f"Bearer {os.environ['NTFY_TOKEN']}"
    _post(f'{server}/{topic}', body.encode('utf-8'), headers)
    return True


def send_telegram(title, body):
    token, chat = os.environ.get('TELEGRAM_BOT_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat:
        return False
    for part in _chunks(f'{title}\n{body}', 4000):
        _post(f'https://api.telegram.org/bot{token}/sendMessage',
              json.dumps({'chat_id': chat, 'text': part, 'disable_web_page_preview': True}).encode(),
              {'Content-Type': 'application/json'})
    return True


def send_discord(title, body):
    url = os.environ.get('DISCORD_WEBHOOK_URL')
    if not url:
        return False
    for part in _chunks(f'**{title}**\n{body}', 1900):
        _post(url, json.dumps({'content': part}).encode(), {'Content-Type': 'application/json'})
    return True


def send_email(title, body):
    sender, password = os.environ.get('EMAIL_SENDER'), os.environ.get('EMAIL_PASSWORD')
    receivers = [r.strip() for r in os.environ.get('EMAIL_RECEIVERS', sender or '').split(',') if r.strip()]
    if not sender or not password or not receivers:
        return False
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'], msg['From'], msg['To'] = title, sender, ', '.join(receivers)
    server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    port = int(os.environ.get('SMTP_PORT', '465'))
    with smtplib.SMTP_SSL(server, port, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, receivers, msg.as_string())
    return True


CHANNELS = {'ntfy': send_ntfy, 'telegram': send_telegram, 'discord': send_discord, 'email': send_email}


def send_all(title, body):
    sent = []
    for name, fn in CHANNELS.items():
        try:
            if fn(title, body):
                sent.append(name)
        except Exception as exc:  # a broken channel must not block the others
            print(f'{name} notification failed: {exc}', file=sys.stderr)
    return sent


if __name__ == '__main__':
    title = sys.argv[1] if len(sys.argv) > 1 else 'Agentic Trader'
    print(send_all(title, sys.stdin.read()) or 'no channel configured')
