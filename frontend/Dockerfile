FROM node:22-alpine AS base

WORKDIR /app

# Install pnpm
RUN npm install -g pnpm

# Install dependencies
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

# Copy application code
COPY . .

EXPOSE 3000

CMD ["pnpm", "dev"]
