import xml.etree.ElementTree as ET
import requests

sitemap = requests.get('https://docs.astral.sh/uv/sitemap.xml', timeout=10)
sitemap.raise_for_status()
root = ET.fromstring(sitemap.text)
ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
targets = []
for url in root.findall('sm:url', ns):
    loc = url.find('sm:loc', ns).text
    targets.append(loc)

hits = []
for loc in targets:
    try:
        resp = requests.get(loc, timeout=10)
        if 'link-mode' in resp.text or 'UV_LINK_MODE' in resp.text:
            hits.append(loc)
    except Exception as exc:
        print('failed', loc, exc)

for loc in hits:
    print(loc)
