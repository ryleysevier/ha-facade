ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip
COPY requirements.txt /
RUN pip3 install --no-cache-dir --break-system-packages -r /requirements.txt

COPY run.py /

CMD ["python3", "-u", "/run.py"]
