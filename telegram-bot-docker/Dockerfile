# Use a minimal Python base image (adjust version if needed)
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy your requirements file (if you have one)
COPY requirements.txt .

# Install Python dependencies (if you have any)
RUN pip install -r requirements.txt

# Copy your Python script (replace with your actual script name)
COPY main.py .

# Copy all files from the current directory to the container (adjust if needed)
COPY . .

# Expose the port your Telegram bot listens on (adjust if needed - Replace with your bot's port number)
EXPOSE 8443  

# Specify the command to run your bot script
CMD [ "python", "main.py" ]