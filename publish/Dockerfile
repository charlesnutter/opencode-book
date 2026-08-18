FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    pandoc \
    calibre \
    python3 \
    python3-pip \
    python3-pil \
    fonts-dejavu-core \
    epubcheck \
    default-jre-headless \
    unzip \
    weasyprint \
    && rm -rf /var/lib/apt/lists/*

# The Debian epubcheck package ships a broken /usr/bin/epubcheck: it's a
# symlink to a jar, not a launcher script, so it doesn't run as a shell
# command. Replace the symlink with a real wrapper script, pointing at the
# untouched jar copy under maven-repo.
RUN rm -f /usr/bin/epubcheck \
    && printf '#!/bin/sh\nexec java -jar /usr/share/maven-repo/org/w3c/epubcheck/4.2.6/epubcheck-4.2.6.jar "$@"\n' > /usr/bin/epubcheck \
    && chmod +x /usr/bin/epubcheck

WORKDIR /work

CMD ["/bin/bash"]
