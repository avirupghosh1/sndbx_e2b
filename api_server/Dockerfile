FROM python:3.11-slim

WORKDIR /app

# Install Docker CLI
RUN apt-get update && \
    apt-get install -y docker.io curl && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

RUN chmod +x /app/docker-entrypoint.sh

# Expose port
EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
# Run the application (passed as args to entrypoint)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
