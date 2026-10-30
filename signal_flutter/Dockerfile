FROM debian:bookworm-slim AS build
ARG FLUTTER_VERSION=3.47.9
ENV FLUTTER_SUPPRESS_ANALYTICS=true CI=true
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git unzip xz-utils python3 libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "$FLUTTER_VERSION" https://github.com/flutter/flutter.git /opt/flutter
ENV PATH="/opt/flutter/bin:${PATH}"
RUN flutter precache --web --no-ios --no-android --no-linux --no-windows --no-macos
WORKDIR /app
COPY signal_flutter/pubspec.yaml signal_flutter/pubspec.lock ./
RUN flutter pub get
COPY signal_flutter/ ./
RUN python3 tool/build.py

FROM nginx:1.27-alpine
COPY frontend/nginx-security-*.conf frontend/nginx-usage-http.conf /etc/nginx/snippets/
COPY frontend/nginx-citizens.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build/web /usr/share/nginx/html
EXPOSE 80
