import json
import time
import requests
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime
from xml.etree import ElementTree as ET
from xml.dom import minidom
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_FILE = PROJECT_ROOT / "frihedsbrevetDATA.json"
OUT_DIR = PROJECT_ROOT.parent / "Frihedsbrevet"
OUT_DIR.mkdir(parents=True, exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
BASE = "https://frihedsbrevet.dk/podcasts/"
ORG = "88c335ba-6520-4de0-97b0-ad3a00d192cf"
DELAY = 0.5
ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES)
ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
known_urls = set()
data = {}
if DATA_FILE.exists():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    for pod in data.values():
        for ep in pod.get("episodes", []):
            if ep.get("page_url"):
                known_urls.add(ep["page_url"])
html = requests.get(BASE, headers=HEADERS, timeout=20).text
soup = BeautifulSoup(html, "html.parser")
pod_urls = []
seen = set()
for a in soup.select("a[href*='/podcasts/']"):
    href = a["href"]
    full = urljoin(BASE, href).rstrip("/")
    if full not in seen and full.count("/podcasts/") == 1 and full.split("/podcasts/")[-1]:
        seen.add(full)
        pod_urls.append(full)
def get_episode(ep_url: str):
    if ep_url in known_urls:
        return None
    time.sleep(DELAY)
    try:
        r = requests.get(ep_url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"Failed {ep_url}: {e}")
        return None
    s = BeautifulSoup(r.text, "html.parser")
    btn = s.find("div", {"data-posthog-event": "podcast_play"})
    if not btn:
        return None
    attrs = {}
    for k, v in btn.attrs.items():
        if k.startswith("data-posthog-attr-"):
            key = k[18:].replace("-", "_")
            attrs[key] = v
    if not attrs.get("episode_uuid") or not attrs.get("podcast_uuid"):
        return None
    img = s.find("img", src=lambda x: x and "omnycontent" in x)
    duration_text = btn.find(string=lambda t: t and "min" in t)
    if duration_text and hasattr(duration_text, "parent"):
        duration_text = duration_text.parent.get_text(strip=True)
    duration = duration_text or ""
    desc_block = s.select_one(".podcast__body")
    description = ""
    if desc_block:
        sub = desc_block.find(class_="podcast__body__sub-headline")
        if sub:
            sub.decompose()
        description = "\n".join(p.get_text(strip=True) for p in desc_block.find_all("p"))
    if not description:
        fallback = s.select_one(".c-podcast__episode--body p")
        if fallback:
            description = fallback.get_text(strip=True)
    return {
        "uuid": attrs["episode_uuid"],
        "podcast_uuid": attrs["podcast_uuid"],
        "title": attrs.get("episode") or s.h1.get_text(strip=True),
        "date": attrs.get("published_at", "")[:10].replace("-", " "),
        "duration": duration,
        "image": img["src"] if img else "",
        "page_url": ep_url,
        "stream_url": f"https://traffic.omny.fm/d/clips/{ORG}/{attrs['podcast_uuid']}/{attrs['episode_uuid']}/audio.mp3",
        "description": description.strip()
    }
result = {}
for pod_url in pod_urls:
    slug = pod_url.split("/")[-1]
    r = requests.get(pod_url, headers=HEADERS, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")
    title = (soup.select_one(".podcast-meta__headline") or soup.find("h1"))
    title = title.get_text(strip=True) if title else slug.replace("-", " ").title()
    desc = "\n\n".join(p.get_text(strip=True) for p in soup.select(".podcast__body p"))
    cover_img = soup.find("img", src=lambda x: x and "omnycontent" in x)
    cover = cover_img["src"] if cover_img else ""
    ep_links = [
        "https://frihedsbrevet.dk" + a["href"]
        for a in soup.select("a[href^='/podcasts/']")
        if a["href"].startswith(f"/podcasts/{slug}/")
    ]
    new_eps = [ep for url in ep_links if (ep := get_episode(url))]
    known_urls.update(ep["page_url"] for ep in new_eps)
    old_eps = data.get(slug, {}).get("episodes", [])
    all_eps = old_eps + new_eps
    # Deduplicate by uuid
    unique_eps = {}
    for ep in all_eps:
        if ep["uuid"] not in unique_eps:
            unique_eps[ep["uuid"]] = ep
    all_eps = list(unique_eps.values())
    all_eps.sort(key=lambda x: x.get("date", "0000"), reverse=True)
    result[slug] = {
        "title": title,
        "url": pod_url,
        "description": desc,
        "cover": cover,
        "episodes": all_eps
    }
DATA_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
def prettify(elem):
    rough = ET.tostring(elem, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent=" ")
for slug, pod in result.items():
    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": ITUNES,
        "xmlns:atom": "http://www.w3.org/2005/Atom"
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = pod["title"]
    ET.SubElement(channel, "link").text = pod["url"]
    ET.SubElement(channel, "description").text = pod["description"] or pod["title"]
    ET.SubElement(channel, "language").text = "da"
    ET.SubElement(channel, "pubDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.SubElement(channel, "itunes:author").text = "Frihedsbrevet"
    owner = ET.SubElement(channel, "itunes:owner")
    ET.SubElement(owner, "itunes:name").text = "Frihedsbrevet"
    ET.SubElement(owner, "itunes:email").text = "kontakt@frihedsbrevet.dk"
    ET.SubElement(channel, "itunes:explicit").text = "false"
    ET.SubElement(channel, "itunes:category", {"text": "News"})
    if pod.get("cover"):
        ET.SubElement(channel, "itunes:image", {"href": pod["cover"]})
    for ep in pod["episodes"]:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ep["title"]
        ET.SubElement(item, "link").text = ep["page_url"]
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = ep["uuid"]
        ET.SubElement(item, "enclosure", {
            "url": ep["stream_url"],
            "length": "0",
            "type": "audio/mpeg"
        })
        ep_desc = ep.get("description") or ep["title"]
        ET.SubElement(item, "description").text = ep_desc
        ET.SubElement(item, "itunes:subtitle").text = ep_desc[:255]
        ET.SubElement(item, "itunes:summary").text = ep_desc
        pubdate = ep.get("date", "1 jan 2025")
        try:
            dt = datetime.strptime(pubdate.strip(), "%Y %m %d")
        except:
            try:
                dt = datetime.strptime(pubdate.strip(), "%d %B %Y")
            except:
                try:
                    dt = datetime.strptime(pubdate.strip(), "%d %b %Y")
                except:
                    dt = datetime(2025, 1, 1)
        dt = dt.replace(hour=12)
        ET.SubElement(item, "pubDate").text = dt.strftime("%a, %d %b %Y 12:00:00 +0000")
        duration = ep.get("duration", "30:00")
        if "min" in duration.lower():
            mins = duration.split("min")[0].strip().zfill(2)
            duration = f"{mins}:00"
        ET.SubElement(item, "itunes:duration").text = duration
        image = ep.get("image") or pod.get("cover", "")
        if image:
            ET.SubElement(item, "itunes:image", {"href": image})
        ET.SubElement(item, "itunes:episodeType").text = "full"
    xml = prettify(rss)
    safe_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)
    (OUT_DIR / f"{safe_slug}.rss").write_text(xml, encoding="utf-8")
