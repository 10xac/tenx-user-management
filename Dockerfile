FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY api/ api/
COPY utils/ utils/
COPY review_scripts/ review_scripts/
COPY api/requirements.txt start.sh ./

# Make start script executable
RUN chmod +x start.sh

# Install Python dependencies
RUN pip install --no-cache-dir -r api/requirements.txt

# Expose port
EXPOSE 8120

# Run the application
CMD ["./start.sh"] 