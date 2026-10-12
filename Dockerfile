FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py ./
COPY web ./web
COPY config.example.json ./config.example.json
EXPOSE 8765
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8765", "--cert", "/certs/roku-wall.pem", "--key", "/certs/roku-wall-key.pem"]
