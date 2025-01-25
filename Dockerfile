FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt . 
RUN python -m pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directory for downloads
RUN mkdir -p /var/www/SpotifyDownloader/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py

EXPOSE 5000

# Update the CMD to use eventlet worker
CMD ["gunicorn", "--worker-class", "eventlet", \
     "--workers", "1", "--bind", "0.0.0.0:5000", "wsgi:app"]
