FROM ubuntu:22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    python3 \
    python3-pip

# Install Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# Copy and install Python app
WORKDIR /app
COPY requirements.txt .
RUN pip3 install -r requirements.txt
COPY app.py .

EXPOSE 5000 11434

# At runtime: start Ollama, pull model, then run Flask
CMD bash -c "ollama serve & sleep 5 && ollama pull mistral && python3 app.py"


