# syntax=docker/dockerfile:1
# Build the static frontend, then serve it with Caddy. Caddy also reverse-proxies
# the API paths to the backend, so the app keeps using relative /v1 and /health
# URLs with no CORS and no build-time API host.
FROM node:20-slim AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /web/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 80
