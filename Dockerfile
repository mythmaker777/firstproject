# Why Python 3.12 slim?
# - slim = smaller image (~150MB vs ~900MB for full python)
# - 3.12 has the best async performance improvements relevant to our bot

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install dependencies first (separate layer = faster rebuilds if only code changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY bot.py .
COPY database.py .

# The SQLite database file will be stored in /data
# Mount a persistent volume here in production so data survives container restarts
RUN mkdir -p /data
ENV DB_PATH=/data/tuition.db

# Run the bot
CMD ["python", "bot.py"]
