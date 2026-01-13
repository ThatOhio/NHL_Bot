# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
# fonts-noto-core: provides /usr/share/fonts/truetype/noto/NotoSans-Bold.ttf (note the path might differ slightly)
# fonts-liberation: provides /usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf
# fonts-dejavu-core: provides /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-core \
    fonts-liberation \
    fonts-dejavu-core \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Run main.py when the container launches
CMD ["python", "main.py"]
