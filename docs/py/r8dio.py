import requests
import json
import os
import xml.etree.ElementTree as ET
import xml.dom.minidom
from datetime import datetime

BASE_URL = "https://r8dio.demo.supertusch.com/podcasts"
ITUNES_NAMESPACE = "http://www.itunes.com/dtds/podcast-1.0.dtd"
DATA_FILE = "./docs/r8dioDATA.json"  
RSS_OUTPUT_DIR = "./r8dio"         
INDEX_OUTPUT_DIR = "./docs"         
INDEX_OUTPUT_FILE = "r8dio.json"

os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
os.makedirs(RSS_OUTPUT_DIR, exist_ok=True)
os.makedirs(INDEX_OUTPUT_DIR, exist_ok=True)

ET.register_namespace('itunes', ITUNES_NAMESPACE)

def seconds_to_hhmmss(seconds):
    """Convert seconds to HH:MM:SS or MM:SS format."""
    hours, remainder = divmod(round(float(seconds)), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours == 0:
        return "{:02d}:{:02d}".format(minutes, seconds)
    else:
        return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)

def datetime_to_rfc822(dt):
    """Convert datetime to RFC 822 format."""
    return dt.strftime('%a, %d %b %Y %H:%M:%S +0000')

def fetch_podcast_data():
    """Fetch podcast data and episodes from the API."""
    print(f"Fetching data from {BASE_URL}")
    response = requests.get(BASE_URL)
    if response.status_code != 200:
        print(f"Kunne ikke hente data. Statuskode: {response.status_code}")
        return None
    
    data = response.json()
    updated_podcasts_info = []
    
    for entry in data:
        try:
            slug = entry.get('slug', 'N/A')
            episodes_url = f"{BASE_URL}/{slug}/episodes"
            program_url = f"https://r8dio.dk/program/{slug}"
            print(f"Fetching episodes for podcast {entry['title']} (slug: {slug})")
            episodes_response = requests.get(episodes_url)
            
            if episodes_response.status_code == 200:
                episodes = episodes_response.json()
                updated_podcasts_info.append({
                    'title': entry['title'],
                    'image': entry.get('image', 'N/A'),
                    'content': entry.get('content', 'N/A'),
                    'slug': slug,
                    'url': episodes_url,
                    'program_url': program_url,
                    'episodes': episodes
                })
                print(f"Episoder blev tilføjet succesfuldt til podcast: {entry['title']}")
            else:
                print(f"Kunne ikke hente episoder for podcast '{entry['title']}'. Statuskode: {episodes_response.status_code}")
        except Exception as e:
            print(f"Der opstod en fejl under behandling af podcast: {entry.get('title', 'ukendt')}. Fejl: {e}")
    
    try:
        with open(DATA_FILE, "w", encoding='utf-8') as file:
            json.dump(updated_podcasts_info, file, indent=2, ensure_ascii=False)
        print(f"Data gemt i '{DATA_FILE}' (absolute: {os.path.abspath(DATA_FILE)})")
    except Exception as e:
        print(f"Fejl ved lagring af datafil: {e}")
        raise
    
    return updated_podcasts_info

def generate_rss(podcast_data):
    """Generate RSS feed for a single podcast."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    
    title = ET.SubElement(channel, "title")
    title.text = podcast_data['title'].strip()
    link = ET.SubElement(channel, "link")
    link.text = podcast_data['program_url'].strip()
    description = ET.SubElement(channel, "description")
    description.text = podcast_data['content'].strip()
    image = ET.SubElement(channel, "{%s}image" % ITUNES_NAMESPACE)
    image.set("href", podcast_data['image'].strip())
    
    existing_guids = set()
    for episode in podcast_data.get('episodes', []):
        episode_guid = str(episode['id'])
        if episode_guid in existing_guids:
            continue
        item = ET.SubElement(channel, "item")
        episode_title = ET.SubElement(item, "title")
        episode_title.text = episode['title'].strip()
        episode_description = ET.SubElement(item, "description")
        episode_description.text = episode['content'].strip()
        pub_date = ET.SubElement(item, "pubDate")
        pub_date.text = datetime_to_rfc822(datetime.strptime(episode['publishedAt'], '%Y-%m-%dT%H:%M:%S.%fZ')).strip()
        guid = ET.SubElement(item, "guid")
        guid.text = episode_guid
        guid.set("isPermaLink", "false")
        enclosure = ET.SubElement(item, "enclosure")
        enclosure.set("url", episode['premiumAudio'].strip())
        enclosure.set("length", "0")
        enclosure.set("type", "audio/mpeg")
        itunes_duration = ET.SubElement(item, "{%s}duration" % ITUNES_NAMESPACE)
        itunes_duration.text = seconds_to_hhmmss(episode['duration']).strip()
        existing_guids.add(episode_guid)
    
    rss_content = ET.tostring(rss, encoding='utf-8')
    return xml.dom.minidom.parseString(rss_content).toprettyxml(indent=" ")

def generate_rss_files(podcast_data):
    """Generate RSS files for all podcasts."""
    try:
        for podcast in podcast_data:
            rss_filename = f"{RSS_OUTPUT_DIR}/{podcast['slug']}.rss"
            rss_content = generate_rss(podcast)
            with open(rss_filename, 'w', encoding='utf-8') as rss_file:
                rss_file.write(rss_content)
            print(f"RSS-filen '{rss_filename}' blev genereret med succes (absolute: {os.path.abspath(rss_filename)})")
    except Exception as e:
        print(f"Fejl ved generering af RSS-filer: {str(e)}")
        raise

def generate_index(podcast_data):
    """Generate index JSON file (r8dio.json)."""
    try:
        index = []
        for podcast in podcast_data:
            podcast_info = {
                "title": podcast.get('title', ''),
                "content": podcast.get('content', ''),
                "image": podcast.get('image', ''),
                "slug": podcast.get('slug', ''),
                "program_url": podcast.get('program_url', ''),
                "episodes": []
            }
            for episode in podcast.get('episodes', []):
                episode_info = {
                    "title": episode.get('title', ''),
                    "publishedAt": episode.get('publishedAt', ''),
                    "id": episode.get('id', '')
                }
                podcast_info["episodes"].append(episode_info)
            index.append(podcast_info)
        
        output_path = os.path.join(INDEX_OUTPUT_DIR, INDEX_OUTPUT_FILE)
        with open(output_path, 'w', encoding='utf-8') as outfile:
            json.dump(index, outfile, ensure_ascii=False, indent=2)
        print(f"'{output_path}' korrekt genereret (absolute: {os.path.abspath(output_path)})")
    except Exception as e:
        print(f"Fejl ved generering af index: {str(e)}")
        raise

def main():
    """Main function to execute the pipeline."""
    print(f"Starting script in working directory: {os.getcwd()}")
    podcast_data = fetch_podcast_data()
    if not podcast_data:
        print("Afslutter på grund af fejlet datahentning.")
        return
    
    generate_rss_files(podcast_data)
    generate_index(podcast_data)

if __name__ == "__main__":
    main()
