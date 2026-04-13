import os
import django
from urllib.parse import urlparse

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ['USE_S3'] = 'True'
os.environ['AWS_ACCESS_KEY_ID'] = 'fake'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'fake'
os.environ['AWS_STORAGE_BUCKET_NAME'] = 'manimatic-media'
os.environ['AWS_S3_ENDPOINT_URL'] = 'https://db.fake.supabase.co/storage/v1/s3'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

django.setup()

from django.core.files.storage import default_storage

try:
    url = default_storage.url('videos/test.mp4')
    print("GENERATED URL:", url)
except Exception as e:
    print("ERROR:", str(e))
