FROM python:3.12-slim

LABEL io.modelcontextprotocol.server.name="ru.xonta/customs"

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV XONTA_CUSTOMS_DATA=/data \
    PORT=8765
VOLUME ["/data"]
EXPOSE 8765

# stdio by default (for catalogs that run the image locally);
# for HTTP: docker run -p 8765:8765 -e HOST=0.0.0.0 image xonta-customs-mcp --http
CMD ["xonta-customs-mcp"]
