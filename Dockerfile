FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend, frontend dist, and entry point
COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
COPY run.py .

# Create directories
RUN mkdir -p cookies logs

# Expose port
EXPOSE 8000

# Start server
CMD ["python", "run.py"]
