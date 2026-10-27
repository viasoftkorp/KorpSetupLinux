FROM busybox:1.36-musl
COPY sim-app /sim-app
COPY ok /usr/local/bin/curl
COPY ok /usr/local/bin/redis-cli
COPY ok /usr/local/bin/pg_isready
RUN chmod +x /sim-app /usr/local/bin/*
ENTRYPOINT ["/sim-app"]
