# PythonAnywhere WSGI entry point.
# In your PythonAnywhere web app config, set the WSGI file path to this file
# and set the working directory to your project folder.

import sys
import os

# Add the project directory to the Python path
project_home = '/home/dittrime/ParaglidingTracking'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Load environment variables from .env if present
from dotenv import load_dotenv
load_dotenv(os.path.join(project_home, '.env'))

from app import app as application  # noqa: F401
