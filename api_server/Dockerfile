FROM ubuntu:22.04
RUN apt-get update && apt-get install -y curl
WORKDIR /app
COPY . .
ENV NODE_ENV=production
ENV PORT=3000
# Parsed builder used to ignore Dockerfile ENV for sandbox exec; it is now merged into the template row.
# Avoid USER without ``RUN useradd`` — that breaks later steps if anything runs as that user.