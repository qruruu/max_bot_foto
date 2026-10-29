FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build
FROM nginx:1.27-alpine AS citizens
COPY nginx-security-*.conf nginx-usage-http.conf /etc/nginx/snippets/
COPY nginx-citizens.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist-citizens /usr/share/nginx/html
EXPOSE 80
FROM nginx:1.27-alpine AS operators
COPY nginx-security-*.conf nginx-usage-http.conf /etc/nginx/snippets/
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
