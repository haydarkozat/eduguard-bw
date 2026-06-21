FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000

# Dev server for the prototype. Swap to `npm run build && npm start` for prod.
CMD ["npm", "run", "dev"]
