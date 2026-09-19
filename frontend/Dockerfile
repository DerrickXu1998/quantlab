# syntax=docker/dockerfile:1

# Build stage: compile the SPA. This stage is also the frontend test image
# (`docker build --target build ... && docker run ... npx vitest run`).
FROM node:22 AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve stage: static SPA behind nginx, /api/ proxied to the backend service.
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
