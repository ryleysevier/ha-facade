ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip
COPY requirements.txt /
RUN pip3 install --no-cache-dir --break-system-packages -r /requirements.txt

COPY run.py /
COPY need_modifiers.py /
COPY web.py /
COPY dweller-card.js /
COPY run.sh /
RUN chmod a+x /run.sh

ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_REF
ARG BUILD_VERSION

LABEL \
    io.hass.name="Facade" \
    io.hass.description="AI-powered dweller pet that reacts to your smart home via MQTT" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    maintainer="Ryley Sevier" \
    org.opencontainers.image.title="Facade" \
    org.opencontainers.image.description="AI-powered dweller pet that reacts to your smart home via MQTT" \
    org.opencontainers.image.authors="Ryley Sevier" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.source="https://github.com/ryleysevier/ha-facade" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}

CMD ["/run.sh"]
