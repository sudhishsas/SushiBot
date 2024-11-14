import base64
import os

import requests
import yt_dlp
from dotenv import load_dotenv

# Create a folder for tracking audio files
# create file for tracking the file names for easier search.

load_dotenv()

client_id = os.environ.get('Client_ID')
client_secret = os.environ.get('Client_secret')


def get_token():
    return 0
