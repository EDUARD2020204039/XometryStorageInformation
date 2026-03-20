FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG BOT_ENTRYPOINT=main.py
ENV BOT_ENTRYPOINT=${BOT_ENTRYPOINT}

RUN mkdir -p /app/data

CMD ["sh", "-c", "python \"$BOT_ENTRYPOINT\""]
