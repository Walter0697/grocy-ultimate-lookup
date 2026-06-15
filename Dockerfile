FROM node:20.19-bookworm-slim AS codex

RUN npm install -g @openai/codex@0.122.0

FROM python:3.12-slim

WORKDIR /app

COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

EXPOSE 9290
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9290"]
