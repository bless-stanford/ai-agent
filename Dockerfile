FROM python:3.13-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for tokens and temporary files
RUN mkdir -p temp

# Command to run the application
CMD ["python", "bot.py"]