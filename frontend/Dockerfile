# Production static frontend. Same-origin: the SPA calls /api/* and /health/*,
# which nginx proxies to API_UPSTREAM (the in-cluster API Service by default).
FROM node:22.17.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Production builds always use the live API, never the mock store.
ENV VITE_USE_MOCK=false
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27.5-alpine
# No trailing path: nginx forwards the original /api/... or /health/... URI.
ENV API_UPSTREAM=http://friction-desk-api:8080
USER root
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
USER 101
EXPOSE 8080
