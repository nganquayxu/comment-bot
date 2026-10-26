#!/usr/bin/env python3
"""Comment bot helper. Two commands, no third-party packages.

  comment_bot.py fetch               -> prints JSON with recent comments that still need a reply
  comment_bot.py post -              -> reads the drafts JSON from stdin and posts them to Slack,
                                        one comment at a time (a file path also works)

Claude does the part that needs judgement (spam / needs-human / writing replies)
between the two commands. Everything mechanical lives here so it behaves the same
on every run.

Env (fetch): META_PAGE_TOKEN, META_PAGE_ID, IG_USER_ID,
             META_TOKEN_PERSONAL, META_PAGE_ID_PERSONAL, IG_USER_ID_PERSONAL
             YOUTUBE_API_KEY, YT_CHANNEL_ID, YT_CHANNEL_ID_PERSONAL  (YouTube is optional)
             ACCOUNT_NAME (default "Brand"), ACCOUNT_NAME_PERSONAL (default "Expert")
             LOOKBACK_HOURS (default 24)
Env (post):  SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, SLACK_PAUSE (default 4)
Optional:    if SLACK_* are set, `fetch` also hides comments already posted to the channel.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

GRAPH = "https://graph.facebook.com/v21.0"
YOUTUBE = "https://www.googleapis.com/youtube/v3"
LOOKBACK_HOURS = float(os.environ.get("LOOKBACK_HOURS", "24"))
ACCOUNT_NAME = os.environ.get("ACCOUNT_NAME", "Brand")
ACCOUNT_NAME_PERSONAL = os.environ.get("ACCOUNT_NAME_PERSONAL", "Expert")

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID", "")
PAUSE = float(os.environ.get("SLACK_PAUSE", "4"))
ICONS = {
    "Instagram": "https://www.google.com/s2/favicons?domain=instagram.com&sz=128",
    "Facebook": "https://www.google.com/s2/favicons?domain=facebook.com&sz=128",
    "YouTube": "https://www.google.com/s2/favicons?domain=youtube.com&sz=128",
}


# --------------------------------------------------------------------------- Meta
def graph_get(path, token, params):
    url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
        except Exception:
            err = {}
        raise RuntimeError(f"Meta HTTP {e.code} code={err.get('code')} {err.get('message', '')[:120]}")


def parse_time(s):
    s = re.sub(r"\.\d+(?=Z|[+-]\d{2}:?\d{2}$)", "", s)  # drop fractional seconds
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def sources():
    out = []
    for account, ig_id, page_id, token in (
        (ACCOUNT_NAME, os.environ.get("IG_USER_ID"), os.environ.get("META_PAGE_ID"), os.environ.get("META_PAGE_TOKEN")),
        (ACCOUNT_NAME_PERSONAL, os.environ.get("IG_USER_ID_PERSONAL"), os.environ.get("META_PAGE_ID_PERSONAL"),
         os.environ.get("META_TOKEN_PERSONAL")),
    ):
        if not token:
            continue
        if ig_id:
            out.append((account, "Instagram", ig_id, token))
        if page_id:
            out.append((account, "Facebook", page_id, token))
    yt_key = os.environ.get("YOUTUBE_API_KEY")
    if yt_key:
        for account, channel_id in (
            (ACCOUNT_NAME, os.environ.get("YT_CHANNEL_ID")),
            (ACCOUNT_NAME_PERSONAL, os.environ.get("YT_CHANNEL_ID_PERSONAL")),
        ):
            if channel_id:
                out.append((account, "YouTube", channel_id, yt_key))
    return out


def fetch_instagram(account, ig_id, token, since):
    me = graph_get(ig_id, token, {"fields": "username"}).get("username", "")
    media = graph_get(f"{ig_id}/media", token, {
        "limit": 15, "fields": "id,caption,permalink,timestamp,comments_count"}).get("data", [])
    found = []
    for m in media:
        if not m.get("comments_count"):
            continue
        comments = graph_get(f"{m['id']}/comments", token, {
            "limit": 50, "fields": "id,text,username,timestamp,replies{id,username}"}).get("data", [])
        for c in comments:
            if parse_time(c["timestamp"]) < since:
                continue
            if c.get("username") == me:
                continue
            replied = [r.get("username") for r in (c.get("replies") or {}).get("data", [])]
            if me in replied:
                continue
            found.append({
                "id": c["id"], "account": account, "platform": "Instagram",
                "user": "@" + c.get("username", "unknown"),
                "link": m.get("permalink", ""), "post": (m.get("caption") or "")[:120],
                "comment": c.get("text", ""), "created": c["timestamp"],
            })
    return found


def fetch_facebook(account, page_id, token, since):
    fields = ("id,message,permalink_url,created_time,"
              "comments.limit(50).filter(toplevel).order(reverse_chronological)"
              "{id,message,from,created_time,permalink_url,comments.limit(5){from}}")
    posts = graph_get(f"{page_id}/posts", token, {"limit": 10, "fields": fields}).get("data", [])
    found = []
    for p in posts:
        for c in (p.get("comments") or {}).get("data", []):
            if parse_time(c["created_time"]) < since:
                continue
            author = c.get("from") or {}
            if author.get("id") == page_id:
                continue
            nested = [(r.get("from") or {}).get("id") for r in (c.get("comments") or {}).get("data", [])]
            if page_id in nested:
                continue
            found.append({
                "id": c["id"], "account": account, "platform": "Facebook",
                "user": author.get("name") or "Facebook user",
                "link": c.get("permalink_url") or p.get("permalink_url", ""),
                "post": (p.get("message") or "")[:120],
                "comment": c.get("message", ""), "created": c["created_time"],
            })
    return found


# --------------------------------------------------------------------------- Slack
def youtube_get(path, api_key, params):
    url = f"{YOUTUBE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Goog-Api-Key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
        except Exception:
            err = {}
        raise RuntimeError(f"YouTube HTTP {e.code} {err.get('message', '')[:120]}")


def fetch_youtube(account, channel_id, api_key, since):
    """Top-level comments on all videos of the channel (newest first)."""
    threads = youtube_get("commentThreads", api_key, {
        "part": "snippet,replies", "allThreadsRelatedToChannelId": channel_id,
        "order": "time", "maxResults": 100, "textFormat": "plainText"}).get("items", [])
    found = []
    for th in threads:
        top = th["snippet"]["topLevelComment"]
        sn = top["snippet"]
        if parse_time(sn["publishedAt"]) < since:
            continue
        if (sn.get("authorChannelId") or {}).get("value") == channel_id:
            continue
        replies = (th.get("replies") or {}).get("comments", [])
        if any(((r["snippet"].get("authorChannelId") or {}).get("value") == channel_id) for r in replies):
            continue
        video_id = sn.get("videoId") or th["snippet"].get("videoId", "")
        found.append({
            "id": top["id"], "account": account, "platform": "YouTube",
            "user": sn.get("authorDisplayName") or "YouTube user",
            "link": f"https://www.youtube.com/watch?v={video_id}&lc={top['id']}",
            "post": video_id, "comment": sn.get("textOriginal") or sn.get("textDisplay", ""),
            "created": sn["publishedAt"],
        })
    return found


def slack(method, payload):
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json; charset=utf-8"},
    )
    for _ in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", "5")) + 1)
                continue
            raise
        if data.get("ok"):
            return data
        if data.get("error") == "ratelimited":
            time.sleep(5)
            continue
        raise RuntimeError(f"Slack {method} failed: {data.get('error')}")
    raise RuntimeError(f"Slack {method} failed after retries")


def posted_ids():
    """Comment ids already posted: message 1 stores the id as its section block_id."""
    data = slack("conversations.history", {"channel": SLACK_CHANNEL, "limit": 200})
    seen = set()
    for msg in data.get("messages", []):
        for block in msg.get("blocks", []) or []:
            bid = block.get("block_id", "")
            if bid.startswith("cid:"):
                seen.add(bid[4:])
    return seen


def esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def one(s):
    return " ".join(esc(s).split())


# --------------------------------------------------------------------------- commands
def cmd_fetch():
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    comments, errors = [], []
    for account, platform, ident, token in sources():
        try:
            if platform == "Instagram":
                comments += fetch_instagram(account, ident, token, since)
            elif platform == "YouTube":
                comments += fetch_youtube(account, ident, token, since)
            else:
                comments += fetch_facebook(account, ident, token, since)
        except Exception as e:  # one broken source must not stop the others
            errors.append(f"{account}/{platform}: {e}")
    already = 0
    if SLACK_TOKEN and SLACK_CHANNEL:
        try:
            seen = posted_ids()
            before = len(comments)
            comments = [c for c in comments if c["id"] not in seen]
            already = before - len(comments)
        except Exception as e:
            errors.append(f"slack-history: {e}")
    json.dump({"lookback_hours": LOOKBACK_HOURS, "already_in_slack": already,
               "comments": comments, "errors": errors}, sys.stdout, ensure_ascii=False, indent=1)
    print()


def cmd_post(path):
    if not SLACK_TOKEN or not SLACK_CHANNEL:
        sys.exit("SLACK_BOT_TOKEN and SLACK_CHANNEL_ID must be set")
    if path == "-":
        data = json.load(sys.stdin)
    else:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    seen = posted_ids()
    posted = skipped = 0
    first = True
    for sec in data.get("sections", []):
        for it in sec.get("items", []):
            cid = str(it.get("id") or f"{sec.get('platform')}|{it.get('user')}|{it.get('comment')}")[:200]
            if cid in seen:
                skipped += 1
                continue
            if not first:
                time.sleep(PAUSE)
            first = False
            url = "".join(c for c in str(it.get("link") or "") if c not in "<>| \t\r\n")
            link = f"<{url}|Post>" if url else "Post"
            text = f"*{one(it.get('user'))}*  \u00b7  {link}\n_{one(it.get('comment'))}_"
            if it.get("needs_human"):
                text += f"\n:warning: *Needs human:* {one(it.get('reason'))}"
            blocks = [
                {"type": "context", "elements": [
                    {"type": "image", "image_url": ICONS.get(sec.get("platform"), ICONS["Instagram"]),
                     "alt_text": str(sec.get("platform", ""))},
                    {"type": "mrkdwn", "text": f"*{one(sec.get('account'))} \u00b7 {one(sec.get('platform'))}*"},
                ]},
                {"type": "section", "block_id": f"cid:{cid}", "text": {"type": "mrkdwn", "text": text[:2900]}},
            ]
            slack("chat.postMessage", {
                "channel": SLACK_CHANNEL,
                "text": f"{sec.get('account')} \u00b7 {sec.get('platform')}: {it.get('user')}",
                "blocks": blocks, "unfurl_links": False, "unfurl_media": False})
            reply = str(it.get("reply") or "").strip()
            if reply and not it.get("needs_human"):
                slack("chat.postMessage", {"channel": SLACK_CHANNEL, "text": esc(reply),
                                           "unfurl_links": False, "unfurl_media": False})
            posted += 1
    print(f"posted {posted}, skipped {skipped} already in channel")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "fetch":
        cmd_fetch()
    elif len(sys.argv) == 3 and sys.argv[1] == "post":
        cmd_post(sys.argv[2])
    else:
        sys.exit(__doc__)
