# Remotion renderer service
# Based on official Remotion Docker setup for headless rendering

FROM node:22-bookworm

# Install Chromium and FFmpeg dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    ffmpeg \
    fonts-noto-color-emoji \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Set Chromium path for Remotion
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV REMOTION_CHROME_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies (ci for deterministic builds)
RUN npm ci

# Copy source code
COPY . .

# Fail build if TypeScript has errors
RUN npx tsc --noEmit

# Create renders output directory and Remotion cache
RUN mkdir -p /renders /home/node/.remotion \
    && chown -R node:node /renders /home/node/.remotion /app

# Set Remotion cache directory to writable location
ENV REMOTION_CACHE_DIR=/home/node/.remotion

# Non-root user
USER node

# Expose HTTP API port
EXPOSE 3100

# Default command runs the render server
CMD ["node", "server.js"]
