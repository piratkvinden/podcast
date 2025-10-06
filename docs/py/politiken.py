import requests
import json
import os
import xml.etree.ElementTree as ET
import xml.dom.minidom
from datetime import datetime
import time

BASE_URL = "https://politiken.dk/webservice/podcast/channels/"
ITUNES_NAMESPACE = "http://www.itunes.com/dtds/podcast-1.0.dtd"
DATA_FILE = "./docs/politikenDATA.json"  
RSS_OUTPUT_DIR = "./Politiken"       
INDEX_OUTPUT_DIR = "./docs"         
INDEX_OUTPUT_FILE = "politiken.json"

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
    
    podcast_data = response.json()
    
    for podcast in podcast_data:
        try:
            podcast_id = podcast["id"]
            episodes_url = f"{BASE_URL}{podcast_id}/episodes"
            print(f"Fetching episodes for podcast {podcast['name']} (ID: {podcast_id})")
            episodes_response = requests.get(episodes_url)
            
            if episodes_response.status_code == 200:
                episodes_data = episodes_response.json()
                podcast['episodes'] = episodes_data
                print(f"Episoder blev tilføjet succesfuldt til podcast: {podcast['name']}")
            else:
                print(f"Kunne ikke hente episoder for {podcast_id}. Statuskode: {episodes_response.status_code}")
        except Exception as e:
            print(f"Der opstod en fejl under behandling af podcast: {podcast['name']}. Fejl: {e}")
    
    try:
        with open(DATA_FILE, "w", encoding='utf-8') as file:
            json.dump(podcast_data, file, indent=2, ensure_ascii=False)
        print(f"Data gemt i '{DATA_FILE}' (absolute: {os.path.abspath(DATA_FILE)})")
    except Exception as e:
        print(f"Fejl ved lagring af datafil: {e}")
        raise
    
    return podcast_data

def generate_rss(podcast_data):
    """Generate RSS feed for a single podcast."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    
    title = ET.SubElement(channel, "title")
    title.text = podcast_data['name'].strip()
    link = ET.SubElement(channel, "link")
    link.text = podcast_data['sectionUrls'][0].strip()
    description = ET.SubElement(channel, "description")
    description.text = podcast_data['description'].strip()
    
    image_url = (podcast_data['latestEpisode']['imageUrlSquareChannel'].strip() 
                 if podcast_data.get('latestEpisode') and podcast_data['latestEpisode'].get('imageUrlSquareChannel')
                 else "noimage")
    image = ET.SubElement(channel, "{%s}image" % ITUNES_NAMESPACE)
    image.set("href", image_url)
    
    existing_guids = set()
    if 'episodes' in podcast_data and podcast_data['episodes']:
        for episode in podcast_data['episodes']:
            episode_guid = str(episode['guid'])
            if episode_guid in existing_guids:
                continue
            item = ET.SubElement(channel, "item")
            episode_title = ET.SubElement(item, "title")
            episode_title.text = episode['title'].strip()
            episode_description = ET.SubElement(item, "description")
            episode_description.text = episode['description'].strip()
            pub_date = ET.SubElement(item, "pubDate")
            pub_date.text = datetime_to_rfc822(datetime.strptime(episode['publishDate'], '%Y-%m-%dT%H:%M:%S')).strip()
            guid = ET.SubElement(item, "guid")
            guid.text = episode_guid
            guid.set("isPermaLink", "false")
            enclosure = ET.SubElement(item, "enclosure")
            enclosure.set("url", episode['audioFileLink'].strip())
            enclosure.set("length", str(episode['fileSize']))
            enclosure.set("type", episode['mimeType'].strip())
            itunes_duration = ET.SubElement(item, "{%s}duration" % ITUNES_NAMESPACE)
            itunes_duration.text = seconds_to_hhmmss(episode['durationInSecond']).strip()
            existing_guids.add(episode_guid)
    else:
        print(f"Podcast '{podcast_data['name']}' har ingen episoder. RSS-filen vil kun indeholde kanaldetaljer.")
    
    rss_content = ET.tostring(rss, encoding='utf-8')
    return xml.dom.minidom.parseString(rss_content).toprettyxml(indent=" ")

def generate_rss_files(podcast_data):
    """Generate RSS files for all podcasts."""
    try:
        for podcast in podcast_data:
            rss_filename = f"{RSS_OUTPUT_DIR}/{podcast['id']}.rss"
            rss_content = generate_rss(podcast)
            with open(rss_filename, 'w', encoding='utf-8') as rss_file:
                rss_file.write(rss_content)
            print(f"RSS-filen '{rss_filename}' blev genereret med succes (absolute: {os.path.abspath(rss_filename)})")
    except Exception as e:
        print(f"Fejl ved generering af RSS-filer: {str(e)}")
        raise

def generate_index(podcast_data):
    """Generate index JSON file (politiken.json)."""
    try:
        index = []
        for podcast in podcast_data:
            image_url = (podcast['latestEpisode']['imageUrlSquareChannel']
                        if podcast.get('latestEpisode') and podcast['latestEpisode'].get('imageUrlSquareChannel')
                        else "noimage")
            podcast_info = {
                "title": podcast['name'],
                "description": podcast['description'],
                "image": image_url,
                "id": podcast['id'],
                "program_url": podcast['sectionUrls'][0]
            }
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

