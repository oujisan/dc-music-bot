# config.py
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
COMMAND_PREFIX = "!"

YTDL_SEARCH_OPTIONS = {
    'format': 'bestaudio/best',
    'extract_flat': True,
    'playlistend': 50,
    'ignoreerrors': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

YTDL_STREAM_OPTIONS = {
    'format': 'bestaudio/best',
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0'
}

FFMPEG_OPTIONS = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2'
}