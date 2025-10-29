import aiohttp
import asyncio
import os
import json
import xml.etree.ElementTree as ET
import xml.dom.minidom
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

BASE_URL = "https://api.dr.dk/radio/v4/search/series?q=*"
ITUNES_NAMESPACE = "http://www.itunes.com/dtds/podcast-1.0.dtd"
DATA_FILE = "./docs/drDATA.json"            
INDEX_FILE = "./docs/drlyd.json"              
SERIES_CACHE_FILE = "./docs/DRLyd_series_cache.json"  
EPISODE_CACHE_FILE = "./docs/DRLyd_afsnit_cache.json"  
RSS_OUTPUT_DIR = "./DRLyd"         

os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
os.makedirs(os.path.dirname(SERIES_CACHE_FILE), exist_ok=True)
os.makedirs(os.path.dirname(EPISODE_CACHE_FILE), exist_ok=True)
os.makedirs(RSS_OUTPUT_DIR, exist_ok=True)

ET.register_namespace('itunes', ITUNES_NAMESPACE)

def load_existing_data(file_path):
    """Load existing JSON data from a file."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Fejl ved læsning af {file_path}: {e}")
            return []
    return []

def save_data(file_path, data):
    """Save data to a JSON file."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Data gemt i '{file_path}' (absolute: {os.path.abspath(file_path)})")
    except Exception as e:
        print(f"Fejl ved lagring af {file_path}: {e}")
        raise

async def fetch_with_retries(session, url, headers, retries=3, backoff=1):
    """Fetch data with retries for rate limits and errors."""
    attempt = 0
    while attempt < retries:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 404:
                    print(f"404 - ingen flere sider for {url}")
                    return None
                elif response.status == 429:
                    wait = float(response.headers.get('Retry-After', backoff * (2 ** attempt)))
                    print(f"Rate limit nået for {url}, venter {wait}s (forsøg {attempt + 1}/{retries})")
                    await asyncio.sleep(wait)
                    attempt += 1
                    continue
                elif response.status == 403:
                    print(f"Forbudt adgang til {url}: {response.status}")
                    return None
                elif response.status == 401:
                    print(f"Afvist for {url}, forsøger igen (forsøg {attempt + 1}/{retries})")
                    await asyncio.sleep(0.5)
                    attempt += 1
                    continue
                elif response.status == 200:
                    return await response.json()
                else:
                    print(f"Fejl ved {url}: {response.status} (forsøg {attempt + 1}/{retries})")
                    await asyncio.sleep(backoff * (2 ** attempt))
                    attempt += 1
        except Exception as e:
            print(f"Fejl ved {url}: {e} (forsøg {attempt + 1}/{retries})")
            await asyncio.sleep(backoff * (2 ** attempt))
            attempt += 1
    print(f"Maks forsøg nået for {url}. Afbryder.")
    return None

async def extract_image_from_rss(session, podcast_url):
    """Extract image URL from podcast RSS feed."""
    try:
        async with session.get(podcast_url) as response:
            if response.status == 200:
                content = await response.text()
                root = ET.fromstring(content)
                image_tag = root.find(".//image/url")
                return image_tag.text if image_tag is not None else None
            else:
                print(f"RSS-fejl {podcast_url}: {response.status}")
                return None
    except Exception as e:
        print(f"RSS-fejl ({podcast_url}): {e}")
        return None

async def fetch_all_series_data(existing_data):
    """Fetch all series data with caching."""
    headers = {
        'x-apikey': 'p0JzsEGfZtTEtP4hodkgI2eFKhrxj4X1',
        'Accept-Encoding': 'gzip',
        'Content-Type': 'application/json',
        'User-Agent': 'okhttp/4.12.0'
    }
    series_data = existing_data.copy()
    existing_hashes = {item['series_hash'] for item in existing_data if 'series_hash' in item}
    cache = load_existing_data(SERIES_CACHE_FILE)
    cache_dict = {item['series_hash']: item.get('last_modified') for item in cache}
    new_cache = []

    limit = 100
    offset = 0
    async with aiohttp.ClientSession() as session:
        while True:
            url = f"{BASE_URL}&limit={limit}&offset={offset}"
            print(f"Henter side: {url}")
            data = await fetch_with_retries(session, url, headers)
            if not data:
                break
            items = data.get('items', [])
            if not items:
                print("Ingen flere elementer.")
                break
            for item in items:
                series_hash = item.get('id')
                if not series_hash or series_hash in existing_hashes:
                    continue
                last_modified = item.get('modified', '')
                if series_hash in cache_dict and cache_dict[series_hash] == last_modified:
                    print(f"Skipping uændret serie: {item.get('title')} (ID: {series_hash})")
                    continue
                podcast_url = item.get('podcastUrl')
                description = item.get('description')
                program_url = item.get('presentationUrl')
                name = item.get('title')
                image_url = None
                image_assets = item.get('imageAssets', [])
                for asset in image_assets:
                    if asset.get('target') == 'Default' and asset.get('ratio') == '1:1':
                        urn_id = asset.get('id').split(':')[-1]
                        image_url = f"https://asset.dr.dk/drlyd/images/urn:dr:radio:image:{urn_id}"
                        break
                if not image_url and image_assets:
                    fallback_asset = image_assets[0]
                    image_url = f"https://www.dr.dk/imagescaler01/{fallback_asset.get('id')}?w=640&h=360"
                if not image_url and podcast_url:
                    image_url = await extract_image_from_rss(session, podcast_url)
                series_data.append({
                    "name": name,
                    "url": podcast_url,
                    "image": image_url,
                    "description": description,
                    "program_url": program_url,
                    "series_hash": series_hash
                })
                new_cache.append({"series_hash": series_hash, "last_modified": last_modified})
                print(f"Tilføjet: {name} (ID: {series_hash})")
                existing_hashes.add(series_hash)
            offset += limit
    save_data(SERIES_CACHE_FILE, new_cache)
    print(f"Samlet antal hentede podcasts: {len(series_data)}")
    return series_data

async def fetch_podcast_links(session, series_hash):
    """Fetch episode page links for a series."""
    base_url = f"https://api.dr.dk/radio/v4/pages/series/{series_hash}"
    headers = {
        'x-apikey': 'p0JzsEGfZtTEtP4hodkgI2eFKhrxj4X1',
        'Accept-Encoding': 'gzip',
        'Content-Type': 'application/json',
        'User-Agent': 'okhttp/4.12.0'
    }
    links = set()
    visited_urls = set()
    url = base_url
    while url:
        if url in visited_urls:
            break
        visited_urls.add(url)
        data = await fetch_with_retries(session, url, headers)
        if not data:
            break
        groups = data.get('groups', [])
        for group in groups:
            for link in (group.get('self'), group.get('next')):
                if link:
                    full_url = link if link.startswith('http') else f"https://api.dr.dk{link}"
                    links.add(full_url)
        next_url = data.get('next') or data.get('self')
        if next_url:
            full_url = next_url if next_url.startswith('http') else f"https://api.dr.dk{next_url}"
            url = full_url
        else:
            url = None
    return links

async def fetch_episodes_from_links(session, links):
    """Fetch episodes from paginated links."""
    episodes = []
    headers = {
        'x-apikey': 'p0JzsEGfZtTEtP4hodkgI2eFKhrxj4X1',
        'Accept-Encoding': 'gzip',
        'Content-Type': 'application/json',
        'User-Agent': 'okhttp/4.12.0'
    }
    cache = load_existing_data(EPISODE_CACHE_FILE)
    cache_dict = {item['url']: item.get('last_modified') for item in cache}
    new_cache = cache.copy()

    async def fetch_page(url, offset):
        url_with_offset = add_offset(url, offset)
        data = await fetch_with_retries(session, url_with_offset, headers)
        return data

    tasks = []
    for link in links:
        offset = 0
        while True:
            url_with_offset = add_offset(link, offset)
            if url_with_offset in cache_dict:
                print(f"Skipping uændret side: {url_with_offset}")
                break
            print(f"Henter afsnit fra: {url_with_offset}")
            tasks.append(fetch_page(link, offset))
            if offset == 0:
                data = await fetch_page(link, offset)
                if not data or not data.get('items', []):
                    break
                if len(data['items']) < 16:
                    break
                offset += 16
            else:
                break
        if len(tasks) >= 10:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for data in results:
                if isinstance(data, dict) and data.get('items'):
                    for item in data['items']:
                        episode_url = item.get('presentationUrl')
                        last_modified = item.get('modified', '')
                        if episode_url in cache_dict and cache_dict[episode_url] == last_modified:
                            continue
                        episode = {
                            'title': item.get('title'),
                            'description': item.get('description'),
                            'audioAssets': item.get('audioAssets', []),
                            'publishTime': item.get('publishTime'),
                            'url': episode_url,
                            'duration': item.get('durationMilliseconds'),
                            'last_modified': last_modified
                        }
                        episodes.append(episode)
                        new_cache.append({"url": episode_url, "last_modified": last_modified})
            tasks = []
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for data in results:
            if isinstance(data, dict) and data.get('items'):
                for item in data['items']:
                    episode_url = item.get('presentationUrl')
                    last_modified = item.get('modified', '')
                    if episode_url in cache_dict and cache_dict[episode_url] == last_modified:
                        continue
                    episode = {
                        'title': item.get('title'),
                        'description': item.get('description'),
                        'audioAssets': item.get('audioAssets', []),
                        'publishTime': item.get('publishTime'),
                        'url': episode_url,
                        'duration': item.get('durationMilliseconds'),
                        'last_modified': last_modified
                    }
                    episodes.append(episode)
                    new_cache.append({"url": episode_url, "last_modified": last_modified})
    save_data(EPISODE_CACHE_FILE, new_cache)
    return episodes

def add_offset(url, offset):
    """Add offset parameter to URL."""
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    query_params['offset'] = [str(offset)]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse(parsed_url._replace(query=new_query))

def datetime_to_rfc822(dt):
    """Convert datetime to RFC 822 format."""
    return dt.strftime('%a, %d %b %Y %H:%M:%S +0000')

def milliseconds_to_hms(ms):
    """Convert milliseconds to HH:MM:SS format."""
    total_seconds = ms // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def generate_rss(podcast_data):
    """Generate RSS feed for a single podcast."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    
    title = ET.SubElement(channel, "title")
    title.text = podcast_data['name']
    link = ET.SubElement(channel, "link")
    link.text = podcast_data['program_url']
    description = ET.SubElement(channel, "description")
    description.text = podcast_data['description'] or '(ingen beskrivelse)'
    image = ET.SubElement(channel, "{%s}image" % ITUNES_NAMESPACE)
    image.set("href", podcast_data['image'] or 'N/A')
    
    existing_guids = set()
    for episode in podcast_data.get('episodes', []):
        print(f"Behandler episode: {episode.get('title')}")
        episode_guid = episode.get('url') or ''
        if not isinstance(episode_guid, str):
            print("Fejl: Episode GUID er ikke en streng:", episode_guid)
            continue
        if episode_guid in existing_guids:
            print("Dublet springes over:", episode_guid)
            continue
        item = ET.SubElement(channel, "item")
        episode_title = ET.SubElement(item, "title")
        episode_title.text = episode['title'] or '(ingen titel)'
        episode_description = ET.SubElement(item, "description")
        episode_description.text = episode['description'].strip() if episode.get('description') else '(ingen beskrivelse)'
        try:
            episode_duration = ET.SubElement(item, "{%s}duration" % ITUNES_NAMESPACE)
            episode_duration.text = milliseconds_to_hms(int(episode['duration']))
        except (ValueError, TypeError):
            print("Fejl ved konvertering af varighed:", episode.get('duration'))
        try:
            pub_date = ET.SubElement(item, "pubDate")
            pub_date.text = datetime_to_rfc822(datetime.strptime(episode['publishTime'], '%Y-%m-%dT%H:%M:%S%z')).strip()
        except (ValueError, TypeError):
            print("Fejl ved parsing af publishTime:", episode.get('publishTime'))
        guid = ET.SubElement(item, "guid")
        guid.text = episode_guid
        guid.set("isPermaLink", "false")
        try:
            enclosure = ET.SubElement(item, "enclosure")
            hb_mp3 = None
            hb_hls = None
            hb = 0
            for asset in episode.get('audioAssets', []):
                if not isinstance(asset, dict):
                    print("Fejl: Asset er ikke et ordbogsobjekt:", asset)
                    continue
                if asset.get('format') == 'mp3' and asset.get('bitrate', 0) > hb:
                    hb = asset['bitrate']
                    hb_mp3 = asset
                if asset.get('format') == 'HLS' and hb_mp3 is None:
                    hb_hls = asset
            if hb_mp3:
                enclosure.set("url", hb_mp3['url'])
                enclosure.set("length", str(hb_mp3.get('fileSize', 0)))
                enclosure.set("type", "audio/mpeg")
            elif hb_hls:
                enclosure.set("url", hb_hls['url'])
                enclosure.set("length", str(hb_hls.get('fileSize', 0)))
                enclosure.set("type", "audio/x-m4a")
            else:
                print("Ingen passende lydasset fundet for episode:", episode['title'])
        except KeyError as e:
            print(f"Fejl ved adgang til nøgle i asset: {e}")
        existing_guids.add(episode_guid)
    
    rss_content = ET.tostring(rss, encoding='utf-8')
    return xml.dom.minidom.parseString(rss_content).toprettyxml(indent=" ")

def generate_rss_files(podcast_data):
    """Generate RSS files for all podcasts."""
    try:
        for podcast in podcast_data:
            if podcast.get('series_hash'):
                rss_filename = f"{RSS_OUTPUT_DIR}/{podcast['program_url'].rsplit('/', 1)[-1]}.rss"
                rss_content = generate_rss(podcast)
                with open(rss_filename, 'w', encoding='utf-8') as rss_file:
                    rss_file.write(rss_content)
                print(f"RSS-filen '{rss_filename}' blev genereret med succes (absolute: {os.path.abspath(rss_filename)})")
            else:
                print(f"{podcast['name']} skipped (hash==null)")
    except Exception as e:
        print(f"Fejl ved generering af RSS-filer: {str(e)}")
        raise

async def main():
    """Main function to execute the pipeline."""
    print(f"Starting script in working directory: {os.getcwd()}")
    existing_data = load_existing_data(INDEX_FILE)
    series_data = await fetch_all_series_data(existing_data)
    save_data(INDEX_FILE, series_data)
    
    async with aiohttp.ClientSession() as session:
        podcasts = load_existing_data(INDEX_FILE)
        tasks = []
        for podcast in podcasts:
            series_hash = podcast.get('series_hash')
            if series_hash:
                print(f"Behandler podcast: {podcast.get('name')} (ID: {series_hash})")
                links = await fetch_podcast_links(session, series_hash)
                tasks.append(fetch_episodes_from_links(session, links))
            else:
                print(f"Ingen serie-hash fundet for podcast: {podcast.get('name')}")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for podcast, episodes in zip([p for p in podcasts if p.get('series_hash')], results):
            if isinstance(episodes, list):
                if 'episodes' not in podcast:
                    podcast['episodes'] = episodes
                else:
                    podcast['episodes'].extend(episodes)
        save_data(DATA_FILE, podcasts)
    
    generate_rss_files(podcasts)

if __name__ == "__main__":
    asyncio.run(main())
