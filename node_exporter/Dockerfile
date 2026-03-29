ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12
FROM $BUILD_FROM

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
