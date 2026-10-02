"""Brand Streamlit's static index.html at image build time.

Link previews (WhatsApp, Teams, Slack) read only the first HTML and never run the app's JavaScript, so they
showed "Streamlit" with no description or image. This writes the PRISMA title, description and Open Graph tags
into that file and replaces the Streamlit favicon. Usage: python deploy/brand_index.py https://prisma.example.id
"""
import html
import shutil
import sys
from pathlib import Path

import streamlit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import brand

base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else ""
static = Path(streamlit.__file__).parent / "static"
index = static / "index.html"
page = index.read_text(encoding="utf-8")

title, desc = html.escape(brand.NAME), html.escape(brand.FULL_NAME)
image = f"{base}/app/static/brand/logo-512.png"
tags = f"""<title>{title}</title>
    <meta name="description" content="{desc}" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="{title}" />
    <meta property="og:title" content="{title}" />
    <meta property="og:description" content="{desc}" />
    <meta property="og:image" content="{image}" />
    <meta property="og:image:width" content="512" />
    <meta property="og:image:height" content="512" />""" + (f'\n    <meta property="og:url" content="{base}/" />' if base else "")

if "<title>Streamlit</title>" not in page:
    sys.exit("brand_index: <title>Streamlit</title> not found; Streamlit's index.html changed, update this script")
index.write_text(page.replace("<title>Streamlit</title>", tags, 1), encoding="utf-8")
shutil.copyfile(brand.FAVICON, static / "favicon.png")
print(f"brand_index: index.html branded (image {image})")
