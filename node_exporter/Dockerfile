ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python 3 and pip explicitly — the supervisor may inject a base
# image that does not include them (e.g. ghcr.io/home-assistant/amd64-base).
RUN apk add --no-cache python3 py3-pip

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY app/ ./app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
