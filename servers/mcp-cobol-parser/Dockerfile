# -----------------------------
# mcp-cobol-parser / Dockerfile
# Option A: libs on classpath (no maven shading)
# -----------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC

# System deps (JDK needed to compile CLI)
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      openjdk-21-jdk-headless \
      tini \
      ca-certificates \
      curl; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Copy project metadata & sources BEFORE install
COPY pyproject.toml ./
COPY README.md ./
COPY mcp_cobol_parser/ ./mcp_cobol_parser/
# Java sources for the small bridge CLIs
COPY vendor-src/proleap/ ./vendor-src/proleap/

# --- Install python deps
RUN pip install --upgrade pip && \
    pip install --no-cache-dir "mcp>=1.0.0" && \
    pip install --no-cache-dir .

# --- Non-root user
RUN useradd -ms /bin/bash appuser && mkdir -p /app/.cache && chown -R appuser:appuser /app
USER appuser

# --- Prepare ProLeap runtime libs
RUN mkdir -p /app/vendor/proleap/lib

# Pull exact versions; ANTLR runtime MUST be 4.7 to match generated parser
RUN set -eux; \
  cd /app/vendor/proleap/lib; \
  # ProLeap core
  curl -fsSL -O https://maven.scijava.org/content/repositories/public/io/github/uwol/proleap-cobol-parser/2.4.0/proleap-cobol-parser-2.4.0.jar; \
  # ANTLR runtime (pin to 4.7 to avoid mismatch with generated code)
  curl -fsSL -O https://repo1.maven.org/maven2/org/antlr/antlr4-runtime/4.7/antlr4-runtime-4.7.jar; \
  # Other dependencies commonly required by ProLeap
  curl -fsSL -O https://repo1.maven.org/maven2/com/google/guava/guava/33.2.1-jre/guava-33.2.1-jre.jar; \
  curl -fsSL -O https://repo1.maven.org/maven2/commons-io/commons-io/2.15.1/commons-io-2.15.1.jar; \
  curl -fsSL -O https://repo1.maven.org/maven2/org/apache/commons/commons-lang3/3.14.0/commons-lang3-3.14.0.jar; \
  curl -fsSL -O https://repo1.maven.org/maven2/org/apache/logging/log4j/log4j-api/2.22.1/log4j-api-2.22.1.jar; \
  curl -fsSL -O https://repo1.maven.org/maven2/org/apache/logging/log4j/log4j-core/2.22.1/log4j-core-2.22.1.jar

# --- Compile the tiny CLI launcher (renova) and richer JSON CLI (astra) and jar them up
# NOTE: CLI.java is at vendor-src/proleap/CLI.java; JsonCli.java is in mcp_cobol_parser/java/
RUN set -eux; \
  test -f /app/vendor-src/proleap/CLI.java; \
  test -f /app/mcp_cobol_parser/java/JsonCli.java; \
  mkdir -p /app/vendor/proleap/build; \
  javac -proc:none -cp "/app/vendor/proleap/lib/*" \
        -d /app/vendor/proleap/build \
        /app/vendor-src/proleap/CLI.java \
        /app/mcp_cobol_parser/java/JsonCli.java; \
  jar --create --file /app/vendor/proleap/proleap-bridge.jar -C /app/vendor/proleap/build .

# --- Defaults
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 \
    PAGE_SIZE=100 \
    MAX_PAGE_SIZE=500 \
    WORKERS=8 \
    CACHE_DIR=/app/.cache \
    LOG_LEVEL=INFO \
    # We’re not wiring cb2xml yet; STRICT_CB2XML=true will fail fast if asked.
    CB2XML_JAR= \
    CB2XML_CP= \
    CB2XML_MAIN= \
    # ProLeap: use our freshly built bridge + libs
    PROLEAP_JAR=/app/vendor/proleap/proleap-bridge.jar \
    PROLEAP_CP=/app/vendor/proleap/lib/* \
    # Default to the richer JSON bridge
    PROLEAP_MAIN=com.astra.proleap.JsonCli \
    # Keep strict so we never silently fall back
    STRICT_PROLEAP=true \
    STRICT_CB2XML=true

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD bash -lc 'exec 3<>/dev/tcp/127.0.0.1/8765 && exec 3>&- || exit 1'

ENTRYPOINT ["/usr/bin/tini","-g","--"]
CMD ["python","-m","mcp_cobol_parser.server"]