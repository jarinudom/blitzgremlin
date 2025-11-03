"""BlitzGremlin - Yahoo Fantasy Football API."""
import logging
from flask import Flask

from config import FLASK_SECRET_KEY, PORT
from routes import register_all_routes

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Create Flask app
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

# Register all routes
register_all_routes(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
